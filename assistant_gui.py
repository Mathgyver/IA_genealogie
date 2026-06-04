import csv
import os
import re
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk
import ollama

# --- CONFIGURATION INITIALE ---
DOSSIER_EXPORT = r"F:\Genealogie_IA"
MODELE_IA = "gemma2:2b"

TRADUCTION_DATES = {
    "JAN": "janvier", "FEB": "février", "MAR": "mars", "APR": "avril",
    "MAY": "mai", "JUN": "juin", "JUL": "juillet", "AUG": "août",
    "SEP": "septembre", "OCT": "octobre", "NOV": "novembre", "DEC": "décembre",
}

# --- FONCTIONS REPRISES DU MOTEUR MAISON ---

def nettoyer_nom_heredis(ligne_name):
    nom_brut = ligne_name.replace("1 NAME ", "").strip()
    if "/" in nom_brut:
        return " ".join(nom_brut.replace("/", " ", 1).replace("/", "").split())
    return nom_brut

def charger_gedcom_maison(chemin):
    if not chemin or not os.path.exists(chemin):
        return {}, []
    with open(chemin, "r", encoding="utf-8-sig", errors="ignore") as f:
        lignes = f.readlines()
    individus, familles = {}, []
    bloc_courant = None
    type_bloc = None
    for ligne in lignes:
        ligne_propre = ligne.strip()
        if ligne_propre.startswith("0 "):
            if bloc_courant:
                if type_bloc == "INDI": individus[bloc_courant["id"]] = bloc_courant
                elif type_bloc == "FAM": familles.append(bloc_courant)
            elements = ligne_propre.split(" ")
            if len(elements) >= 3:
                id_bloc, tag_bloc = elements[1].strip(), elements[2].strip()
                if tag_bloc == "INDI":
                    type_bloc = "INDI"
                    bloc_courant = {"id": id_bloc, "nom": "Inconnu", "lignes": [], "parents_familles": []}
                elif tag_bloc == "FAM":
                    type_bloc = "FAM"
                    bloc_courant = {"id": id_bloc, "lignes": [], "husband": None, "wife": None}
                else: bloc_courant = None
            else: bloc_courant = None
        elif bloc_courant and not ligne_propre.startswith("0 "):
            bloc_courant["lignes"].append(ligne_propre)
            if type_bloc == "INDI":
                if ligne_propre.startswith("1 NAME "): bloc_courant["nom"] = nettoyer_nom_heredis(ligne_propre)
                elif ligne_propre.startswith("1 FAMC "): bloc_courant["parents_familles"].append(ligne_propre.replace("1 FAMC ", "").strip())
            elif type_bloc == "FAM":
                if ligne_propre.startswith("1 HUSB "): bloc_courant["husband"] = ligne_propre.replace("1 HUSB ", "").strip()
                elif ligne_propre.startswith("1 WIFE "): bloc_courant["wife"] = ligne_propre.replace("1 WIFE ", "").strip()
    if bloc_courant:
        if type_bloc == "INDI": individus[bloc_courant["id"]] = bloc_courant
        elif type_bloc == "FAM": familles.append(bloc_courant)
    return individus, familles

def interroger_ia_pour_filtres(phrase_utilisateur):
    """Demande à l'IA d'extraire les critères avec un prompt ultra-rigide."""
    prompt = f"""
    Tu es un extracteur de données généalogiques strict. Tu dois analyser la demande et extraire les variables sous cette forme exacte.
    Ne tape aucun autre texte, pas de gras, pas de blabla.

    MODELE DE REPONSE :
    COMMUNE: nom de la commune ou None
    EVENEMENT: BIRT pour naissance, DEAT pour décès, MARR pour mariage, ou None
    ANNEE_DEBUT: année sur 4 chiffres ou None
    ANNEE_FIN: année sur 4 chiffres ou None
    FILTRE_SOURCE: MANQUANTE si l'acte est non sourcé/manquant, sinon TOUT
    FILTRE_DATE: PRECISE ou TOUT
    ASCENDANCE_DE: Nom complet si mentionné, sinon None

    Demande à analyser : "{phrase_utilisateur}"
    """
    try:
        reponse = ollama.chat(model=MODELE_IA, messages=[{"role": "user", "content": prompt}])
        texte_ia = reponse['message']['content']
        
        filtres = {c: None for c in ["COMMUNE", "EVENEMENT", "ANNEE_DEBUT", "ANNEE_FIN", "FILTRE_SOURCE", "FILTRE_DATE", "ASCENDANCE_DE"]}
        
        for ligne in texte_ia.split("\n"):
            if ":" in ligne:
                c, v = ligne.split(":", 1)
                c_p = c.replace("*", "").replace("-", "").strip().upper()
                v_p = v.replace("*", "").strip()
                if c_p in filtres:
                    filtres[c_p] = None if v_p.upper() in ["NONE", "NONE.", ""] else v_p
                    
        # --- SECURITE MANUELLE ABSOLUE (Anti-dérapage de l'IA) ---
        p_lower = phrase_utilisateur.lower()
        if "naiss" in p_lower or "né" in p_lower:
            filtres["EVENEMENT"] = "BIRT"
        elif "mari" in p_lower or "épou" in p_lower:
            filtres["EVENEMENT"] = "MARR"
        elif "décè" in p_lower or "mort" in p_lower or "décéd" in p_lower:
            filtres["EVENEMENT"] = "DEAT"
            
        return filtres
    except:
        return None

def analyser_evenement_maison(lignes_bloc, tag_evenement):
    info = {"trouve": False, "date": "Inconnue", "lieu": "Inconnu", "a_source": False, "precision": "Inconnue"}
    dans_ev = False
    a_src = False
    for ligne in lignes_bloc:
        if ligne.startswith(f"1 {tag_evenement}"):
            dans_ev = True
            info["trouve"] = True
            continue
        if dans_ev:
            if ligne.startswith("2 DATE "): info["date"] = ligne.replace("2 DATE ", "").strip()
            elif ligne.startswith("2 PLAC "): info["lieu"] = ligne.replace("2 PLAC ", "").strip()
            elif "SOUR" in ligne: a_src = True
            elif ligne.startswith("1 "): dans_ev = False
    if info["trouve"]:
        info["a_source"] = a_src
        approx = any(k in info["date"].upper() for k in ["ABT", "BEF", "AFT", "BET", "CALC", "EST"]) or (len(info["date"].split())==1 and info["date"].split()[0].isdigit())
        info["precision"] = "Approximative" if approx else "Précise"
    return info

def est_annee_dans_fourchette(date_str, deb, fin):
    if not date_str or date_str == "Inconnue": return False
    annees = [int(s) for s in re.findall(r'\b\d{4}\b', date_str)]
    if not annees: return False
    annee = annees[0]
    if deb and fin: return int(deb) <= annee <= int(fin)
    if deb: return annee >= int(deb)
    if fin: return annee <= int(fin)
    return True

def recuperer_ascendance_maison(id_depart, individus, fam_liste, ancetres=None):
    if ancetres is None: ancetres = set()
    if id_depart not in individus or id_depart in ancetres: return None
    ancetres.add(id_depart)
    for f_id in individus[id_depart]["parents_familles"]:
        for f in fam_liste:
            if f["id"] == f_id:
                if f["husband"]: recuperer_ascendance_maison(f["husband"], individus, fam_liste, ancetres)
                if f["wife"]: recuperer_ascendance_maison(f["wife"], individus, fam_liste, ancetres)
    return ancetres

# --- INTERFACE GRAPHIQUE MODERNE ---
class AppAssistant(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Configuration de la fenêtre principale
        self.title("Généalogie IA — Assistant RAG Local")
        self.geometry("1000x720")
        ctk.set_appearance_mode("dark") # Mode sombre par défaut
        ctk.set_default_color_theme("blue")
        
        # Initialisation des variables de données
        self.chemin_gedcom_actuel = None
        self.individus = {}
        self.familles = []
        self.filtres_ia = {}
        self.individus_trouves_homonymes = []
        
        # Layout principal (Grille)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1) # Ajustement de l'index de ligne pour le tableau
        
        # --- ZONE 0 : SELECTION DU FICHIER GEDCOM ---
        self.frame_fichier = ctk.CTkFrame(self, corner_radius=10, fg_color="#1e1e1e")
        self.frame_fichier.grid(row=0, column=0, padx=20, pady=(15, 5), sticky="ew")
        
        self.btn_ouvrir_gedcom = ctk.CTkButton(
            self.frame_fichier, 
            text="📁 Choisir un fichier GEDCOM", 
            command=self.ouvrir_fichier_gedcom, 
            width=220, 
            fg_color="#1f538d",
            hover_color="#14375e",
            font=ctk.CTkFont(weight="bold")
        )
        self.btn_ouvrir_gedcom.pack(side="left", padx=15, pady=10)
        
        self.label_statut_gedcom = ctk.CTkLabel(
            self.frame_fichier, 
            text="Aucun fichier généalogique chargé actuellement.", 
            text_color="gray", 
            font=ctk.CTkFont(slant="italic")
        )
        self.label_statut_gedcom.pack(side="left", padx=10, pady=10)
        
        # --- ZONE 1 : BARRE DE RECHERCHE ---
        self.frame_recherche = ctk.CTkFrame(self, corner_radius=10)
        self.frame_recherche.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        self.frame_recherche.grid_columnconfigure(0, weight=1)
        
        self.lbl_titre = ctk.CTkLabel(self.frame_recherche, text="Quelle liste souhaitez-vous extraire ?", font=ctk.CTkFont(size=14, weight="bold"))
        self.lbl_titre.grid(row=0, column=0, padx=15, pady=(10,5), sticky="w")
        
        self.entry_demande = ctk.CTkEntry(self.frame_recherche, placeholder_text="Ex: dans l'ascendance de Guy Marie Regis VALLAT, trouve les personnes nées à saint sauveur en rue entre 1650 et 1700 sans source...")
        self.entry_demande.grid(row=1, column=0, padx=15, pady=10, sticky="ew")
        self.entry_demande.bind("<Return>", lambda e: self.analyser_demande())
        
        self.btn_analyser = ctk.CTkButton(self.frame_recherche, text="Analyser avec l'IA", command=self.analyser_demande, width=150, font=ctk.CTkFont(weight="bold"))
        self.btn_analyser.grid(row=1, column=1, padx=15, pady=10)

        # --- ZONE 2 : PANNEL D'HOMONYMES COMPACT (Masqué par défaut) ---
        self.frame_homonymes = ctk.CTkFrame(self, corner_radius=10, fg_color="#2b2b2b")
        self.combo_homonymes = ctk.CTkComboBox(self.frame_homonymes, width=400)
        self.btn_valider_homonyme = ctk.CTkButton(self.frame_homonymes, text="Verrouiller cette branche", command=self.valider_choix_homonyme)

        # --- ZONE 3 : GRILLE DE RÉSULTATS (Tableau) ---
        self.frame_tableau = ctk.CTkFrame(self, corner_radius=10)
        self.frame_tableau.grid(row=3, column=0, padx=20, pady=10, sticky="nsew")
        self.frame_tableau.grid_columnconfigure(0, weight=1)
        self.frame_tableau.grid_rowconfigure(0, weight=1)
        
        # Style du tableau (Treeview standard configuré proprement)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#333333", foreground="white", fieldbackground="#333333", rowheight=26, borderwidth=0)
        style.configure("Treeview.Heading", background="#222222", foreground="white", borderwidth=0, font=('Arial', 10, 'bold'))
        style.map("Treeview", background=[('selected', '#1f538d')])
        
        colonnes = ("id", "nom", "epouse", "evenement", "date", "precision", "lieu", "source")
        self.tree = ttk.Treeview(self.frame_tableau, columns=colonnes, show="headings", selectmode="browse")
        
        # Définition des entêtes
        self.tree.heading("id", text="ID")
        self.tree.heading("nom", text="Nom / Époux")
        self.tree.heading("epouse", text="Épouse")
        self.tree.heading("evenement", text="Événement")
        self.tree.heading("date", text="Date")
        self.tree.heading("precision", text="Précision")
        self.tree.heading("lieu", text="Lieu")
        self.tree.heading("source", text="Statut Source")
        
        # Largeurs colonnes
        self.tree.column("id", width=60, anchor="center")
        self.tree.column("nom", width=180, anchor="w")
        self.tree.column("epouse", width=150, anchor="w")
        self.tree.column("evenement", width=90, anchor="center")
        self.tree.column("date", width=110, anchor="center")
        self.tree.column("precision", width=100, anchor="center")
        self.tree.column("lieu", width=180, anchor="w")
        self.tree.column("source", width=90, anchor="center")
        
        self.tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        # Barre de défilement du tableau
        scrollbar = ttk.Scrollbar(self.frame_tableau, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns", pady=10)
        
        # --- BARRE D'ÉTAT INFÉRIEURE ---
        self.lbl_status = ctk.CTkLabel(self, text="En attente de chargement d'un fichier GEDCOM.", text_color="gray", font=ctk.CTkFont(size=11))
        self.lbl_status.grid(row=4, column=0, padx=20, pady=5, sticky="w")
        
        self.btn_ouvrir_folder = ctk.CTkButton(self, text="📁 Ouvrir le dossier des exports", command=self.ouvrir_dossier_export, fg_color="transparent", border_width=1, text_color="white", hover_color="#333333", width=200)
        self.btn_ouvrir_folder.grid(row=4, column=0, padx=20, pady=5, sticky="e")

    def ouvrir_fichier_gedcom(self):
        # 1. Ouvrir la boîte de dialogue de Windows
        chemin_selectionne = filedialog.askopenfilename(
            title="Sélectionner un fichier généalogique GEDCOM",
            filetypes=[("Fichiers GEDCOM", "*.ged"), ("Tous les fichiers", "*.*")]
        )
        
        # 2. Si l'utilisateur valide un fichier
        if chemin_selectionne:
            self.chemin_gedcom_actuel = chemin_selectionne
            nom_fichier = os.path.basename(chemin_selectionne)
            
            # Mise à jour graphique immédiate
            self.label_statut_gedcom.configure(text=f"Fichier actif : {nom_fichier}", text_color="#2ecc71")
            self.lbl_status.configure(text="⏳ Chargement et indexation de la base généalogique en cours...", text_color="#ff9900")
            self.update()
            
            # Rechargement dynamique des structures en mémoire
            self.individus, self.familles = charger_gedcom_maison(self.chemin_gedcom_actuel)
            self.lbl_status.configure(text=f"✅ Base rechargée avec succès : {len(self.individus)} individus indexés.", text_color="green")

    def ouvrir_dossier_export(self):
        if os.path.exists(DOSSIER_EXPORT):
            os.startfile(DOSSIER_EXPORT)
        else:
            messagebox.showwarning("Dossier introuvable", f"Le dossier d'export spécifié n'existe pas :\n{DOSSIER_EXPORT}")

    def analyser_demande(self):
        if not self.chemin_gedcom_actuel:
            messagebox.showwarning("GEDCOM manquant", "Veuillez d'abord sélectionner un fichier GEDCOM avant d'interroger l'IA.")
            return

        phrase = self.entry_demande.get().strip()
        if not phrase: return
        
        # Réinitialisation de l'interface
        self.frame_homonymes.grid_forget()
        for row in self.tree.get_children(): self.tree.delete(row)
        
        self.lbl_status.configure(text="🧠 L'IA analyse votre demande...", text_color="#ff9900")
        self.update()
        
        self.filtres_ia = interroger_ia_pour_filtres(phrase)
        if not self.filtres_ia or not self.filtres_ia.get("EVENEMENT"):
            self.lbl_status.configure(text="⚠️ Impossible de déterminer les critères de l'événement.", text_color="red")
            return
            
        ascendance_nom = self.filtres_ia.get("ASCENDANCE_DE")
        
        if ascendance_nom:
            self.individus_trouves_homonymes = []
            for i_id, i_obj in self.individus.items():
                if ascendance_nom.lower() in i_obj["nom"].lower():
                    self.individus_trouves_homonymes.append(i_obj)
            
            if len(self.individus_trouves_homonymes) == 0:
                self.executer_filtrage_final(self.individus.copy())
            elif len(self.individus_trouves_homonymes) == 1:
                id_pivot = self.individus_trouves_homonymes[0]['id']
                ids_ancetres = recuperer_ascendance_maison(id_pivot, self.individus, self.familles)
                cible = {i_id: self.individus[i_id] for i_id in ids_ancetres if i_id in self.individus}
                self.executer_filtrage_final(cible, self.individus_trouves_homonymes[0]['nom'])
            else:
                # Affichage du pannel d'homonymes s'il y a plusieurs choix
                self.frame_homonymes.grid(row=2, column=0, padx=20, pady=5, sticky="ew")
                choix_textes = [f"{i['nom']} ({i['id']})" for i in self.individus_trouves_homonymes[:50]]
                self.combo_homonymes.configure(values=choix_textes)
                self.combo_homonymes.set(choix_textes[0])
                
                self.combo_homonymes.grid(row=0, column=0, padx=15, pady=10, sticky="w")
                self.btn_valider_homonyme.grid(row=0, column=1, padx=15, pady=10, sticky="e")
                self.lbl_status.configure(text=f"🤔 {len(self.individus_trouves_homonymes)} homonymes détectés. Veuillez valider le pivot.", text_color="#ff9900")
        else:
            self.executer_filtrage_final(self.individus.copy())

    def valider_choix_homonyme(self):
        texte_selectionne = self.combo_homonymes.get()
        # Extraction de l'ID entre parenthèses
        id_pivot = re.findall(r'\((.*?)\)', texte_selectionne)[-1]
        nom_pivot = texte_selectionne.split(" (")[0]
        
        self.frame_homonymes.grid_forget()
        ids_ancetres = recuperer_ascendance_maison(id_pivot, self.individus, self.familles)
        cible = {i_id: self.individus[i_id] for i_id in ids_ancetres if i_id in self.individus}
        self.executer_filtrage_final(cible, nom_pivot)

    def executer_filtrage_final(self, sous_arbre, nom_contexte="Tout l'arbre"):
        tag_ev = self.filtres_ia.get("EVENEMENT")
        commune = self.filtres_ia.get("COMMUNE", "").lower() if self.filtres_ia.get("COMMUNE") else None
        f_source = self.filtres_ia.get("FILTRE_SOURCE")
        
        if self.filtres_ia.get("ANNEE_DEBUT") or self.filtres_ia.get("ANNEE_FIN"):
            f_date = "TOUT"
        else:
            f_date = self.filtres_ia.get("FILTRE_DATE")
            
        resultats = []

        if tag_ev in ["BIRT", "DEAT"]:
            nom_ev = "Naissance" if tag_ev == "BIRT" else "Décès"
            for ind in sous_arbre.values():
                ev_info = analyser_evenement_maison(ind["lignes"], tag_ev)
                if not ev_info["trouve"]: continue
                if commune and commune not in ev_info["lieu"].lower(): continue
                if (self.filtres_ia.get("ANNEE_DEBUT") or self.filtres_ia.get("ANNEE_FIN")) and not est_annee_dans_fourchette(ev_info["date"], self.filtres_ia.get("ANNEE_DEBUT"), self.filtres_ia.get("ANNEE_FIN")):
                    continue
                if f_source == "MANQUANTE" and ev_info["a_source"]: continue
                if f_date == "PRECISE" and ev_info["precision"] != "Précise": continue
                
                statut_s = "🔴 Manquant" if not ev_info["a_source"] else "🟢 Sourcé"
                
                # Traduction propre de la date (uniquement si elle contient des mois anglais)
                date_fr = ev_info["date"]
                for k, v in TRADUCTION_DATES.items():
                    date_fr = re.sub(r'\b' + k + r'\b', v, date_fr, flags=re.IGNORECASE)
                    
                resultats.append([ind["id"], ind["nom"], "", nom_ev, date_fr, ev_info["precision"], ev_info["lieu"], statut_s])

        elif tag_ev == "MARR":
            for fam in self.familles:
                ev_info = analyser_evenement_maison(fam["lignes"], "MARR")
                if not ev_info["trouve"]: continue
                if commune and commune not in ev_info["lieu"].lower(): continue
                if (self.filtres_ia.get("ANNEE_DEBUT") or self.filtres_ia.get("ANNEE_FIN")) and not est_annee_dans_fourchette(ev_info["date"], self.filtres_ia.get("ANNEE_DEBUT"), self.filtres_ia.get("ANNEE_FIN")):
                    continue
                if f_source == "MANQUANTE" and ev_info["a_source"]: continue
                if f_date == "PRECISE" and ev_info["precision"] != "Précise": continue
                
                nom_mari = self.individus.get(fam["husband"], {}).get("nom", "Inconnu") if fam["husband"] else "Inconnu"
                nom_femme = self.individus.get(fam["wife"], {}).get("nom", "Inconnu") if fam["wife"] else "Inconnu"
                
                if self.filtres_ia.get("ASCENDANCE_DE") and (fam["husband"] not in sous_arbre and fam["wife"] not in sous_arbre):
                    continue
                    
                statut_s = "🔴 Manquant" if not ev_info["a_source"] else "🟢 Sourcé"
                
                date_fr = ev_info["date"]
                for k, v in TRADUCTION_DATES.items():
                    date_fr = re.sub(r'\b' + k + r'\b', v, date_fr, flags=re.IGNORECASE)
                    
                resultats.append([fam["id"], nom_mari, nom_femme, "Mariage", date_fr, ev_info["precision"], ev_info["lieu"], statut_s])

        for item in resultats:
            self.tree.insert("", "end", values=item)
            
        if resultats:
            if not os.path.exists(DOSSIER_EXPORT):
                os.makedirs(DOSSIER_EXPORT)
            nom_csv = os.path.join(DOSSIER_EXPORT, "extraction_demande.csv")
            with open(nom_csv, mode="w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["ID", "Nom / Époux", "Épouse", "Événement", "Date", "Précision", "Lieu", "Source"])
                writer.writerows(resultats)
            self.lbl_status.configure(text=f"✅ {len(resultats)} lignes trouvées pour '{nom_contexte}' (Données sauvegardées).", text_color="green")
        else:
            self.lbl_status.configure(text="❌ Aucune correspondance trouvée.", text_color="red")

if __name__ == "__main__":
    app = AppAssistant()
    app.mainloop()