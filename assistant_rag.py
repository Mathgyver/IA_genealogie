import os
import re
import csv
import ollama

# Configuration
CHEMIN_GEDCOM = r"F:\Genealogie_IA\mon_test.ged"
DOSSIER_EXPORT = r"F:\Genealogie_IA"
MODELE_IA = "gemma2:2b"  # Ton modèle local validé

# Dictionnaire de traduction des mois GEDCOM pour l'affichage
TRADUCTION_DATES = {
    "JAN": "janvier", "FEB": "février", "MAR": "mars", "APR": "avril",
    "MAY": "mai", "JUN": "juin", "JUL": "juillet", "AUG": "août",
    "SEP": "septembre", "OCT": "octobre", "NOV": "novembre", "DEC": "décembre",
}

def nettoyer_nom_heredis(ligne_name):
    """Nettoie les slashes Heredis pour un affichage propre avec espace."""
    nom_brut = ligne_name.replace("1 NAME ", "").strip()
    if "/" in nom_brut:
        nom_nettoye = nom_brut.replace("/", " ", 1).replace("/", "")
        return " ".join(nom_nettoye.split())
    return nom_brut

def charger_gedcom_maison(chemin):
    """Ouvre le GEDCOM et sépare les individus et les structures de familles."""
    if not os.path.exists(chemin):
        print(f"❌ Erreur : Le fichier {chemin} est introuvable.")
        return {}, []
        
    print(f"⚡ Chargement de l'arbre en cours... ({chemin})")
    with open(chemin, "r", encoding="utf-8-sig", errors="ignore") as f:
        lignes = f.readlines()
        
    dictionnaire_individus = {}
    liste_familles = []
    bloc_courant = None
    type_bloc = None
    
    for ligne in lignes:
        ligne_propre = ligne.strip()
        
        if ligne_propre.startswith("0 "):
            if bloc_courant:
                if type_bloc == "INDI":
                    dictionnaire_individus[bloc_courant["id"]] = bloc_courant
                elif type_bloc == "FAM":
                    liste_familles.append(bloc_courant)
            
            elements = ligne_propre.split(" ")
            if len(elements) >= 3:
                id_bloc = elements[1].strip()
                tag_bloc = elements[2].strip()
                
                if tag_bloc == "INDI":
                    type_bloc = "INDI"
                    bloc_courant = {"id": id_bloc, "nom": "Inconnu", "lignes": [], "parents_familles": []}
                elif tag_bloc == "FAM":
                    type_bloc = "FAM"
                    bloc_courant = {"id": id_bloc, "lignes": [], "husband": None, "wife": None}
                else:
                    bloc_courant = None
                    type_bloc = None
            else:
                bloc_courant = None
                type_bloc = None
        
        elif bloc_courant and not ligne_propre.startswith("0 "):
            bloc_courant["lignes"].append(ligne_propre)
            if type_bloc == "INDI":
                if ligne_propre.startswith("1 NAME "):
                    bloc_courant["nom"] = nettoyer_nom_heredis(ligne_propre)
                elif ligne_propre.startswith("1 FAMC "):
                    id_famc = ligne_propre.replace("1 FAMC ", "").strip()
                    bloc_courant["parents_familles"].append(id_famc)
            elif type_bloc == "FAM":
                if ligne_propre.startswith("1 HUSB "):
                    bloc_courant["husband"] = ligne_propre.replace("1 HUSB ", "").strip()
                elif ligne_propre.startswith("1 WIFE "):
                    bloc_courant["wife"] = ligne_propre.replace("1 WIFE ", "").strip()
                
    if bloc_courant:
        if type_bloc == "INDI":
            dictionnaire_individus[bloc_courant["id"]] = bloc_courant
        elif type_bloc == "FAM":
            liste_familles.append(bloc_courant)
        
    print(f"✅ {len(dictionnaire_individus)} individus et {len(liste_familles)} familles chargés.")
    return dictionnaire_individus, liste_familles

def interroger_ia_pour_filtres(phrase_utilisateur):
    """Demande à l'IA d'extraire les critères avec un prompt rigide adapté à Gemma 2."""
    prompt = f"""
    Tu es un outil d'extraction de données généalogiques strict. Tu dois analyser la demande de l'utilisateur et extraire les variables.
    
    Tu devez STRICTEMENT répondre en suivant ce modèle exact, ligne par ligne, sans salutations, sans gras (*), sans explications :
    COMMUNE: le nom de la commune ou None
    EVENEMENT: BIRT pour naissance, DEAT pour décès, MARR pour mariage, ou None
    ANNEE_DEBUT: année sur 4 chiffres ou None
    ANNEE_FIN: année sur 4 chiffres ou None
    FILTRE_SOURCE: MANQUANTE si l'acte est demandé comme manquant/sans source/pas d'acte, sinon TOUT
    FILTRE_DATE: PRECISE ou TOUT
    ASCENDANCE_DE: Nom complet de la personne si ses ancêtres sont ciblés, sinon None

    Exemple : "naissances à Craix sans source dans l'ascendance de Jean Cortial"
    COMMUNE: Craix
    EVENEMENT: BIRT
    ANNEE_DEBUT: None
    ANNEE_FIN: None
    FILTRE_SOURCE: MANQUANTE
    FILTRE_DATE: TOUT
    ASCENDANCE_DE: Jean Cortial

    Demande à analyser : "{phrase_utilisateur}"
    """
    try:
        reponse = ollama.chat(model=MODELE_IA, messages=[{"role": "user", "content": prompt}])
        texte_ia = reponse['message']['content']
        
        filtres = {}
        cles_attendues = ["COMMUNE", "EVENEMENT", "ANNEE_DEBUT", "ANNEE_FIN", "FILTRE_SOURCE", "FILTRE_DATE", "ASCENDANCE_DE"]
        
        # Initialisation par défaut
        for cle in cles_attendues:
            filtres[cle] = None
            
        for ligne in texte_ia.split("\n"):
            if ":" in ligne:
                cle, valeur = ligne.split(":", 1)
                cle_propre = cle.replace("*", "").replace("-", "").strip().upper()
                valeur_propre = valeur.replace("*", "").strip()
                
                if cle_propre in cles_attendues:
                    filtres[cle_propre] = None if valeur_propre.upper() in ["NONE", "NONE.", ""] else valeur_propre
                    
        # Système de secours manuel si l'IA oublie les tags GEDCOM (BIRT/DEAT/MARR)
        if filtres.get("EVENEMENT") and filtres["EVENEMENT"].upper() not in ["BIRT", "DEAT", "MARR"]:
            up_phrase = phrase_utilisateur.lower()
            if "naiss" in up_phrase or "né" in up_phrase: filtres["EVENEMENT"] = "BIRT"
            elif "décè" in up_phrase or "mort" in up_phrase: filtres["EVENEMENT"] = "DEAT"
            elif "mari" in up_phrase or "épou" in up_phrase: filtres["EVENEMENT"] = "MARR"
            
        return filtres
    except Exception as e:
        print(f"⚠️ Erreur de connexion avec l'IA : {e}")
        return None

def analyser_evenement_maison(lignes_bloc, tag_evenement):
    """Extrait les infos d'un événement et calcule la présence de source et la précision."""
    info = {"trouve": False, "date": "Inconnue", "lieu": "Inconnu", "a_source": False, "precision": "Inconnue"}
    dans_evenement = False
    a_cle_source = False
    
    for ligne in lignes_bloc:
        if ligne.startswith(f"1 {tag_evenement}"):
            dans_evenement = True
            info["trouve"] = True
            continue
            
        if dans_evenement:
            if ligne.startswith("2 DATE "):
                info["date"] = ligne.replace("2 DATE ", "").strip()
            elif ligne.startswith("2 PLAC "):
                info["lieu"] = ligne.replace("2 PLAC ", "").strip()
            elif "SOUR" in ligne:
                a_cle_source = True
            elif ligne.startswith("1 "):
                dans_evenement = False
                
    if info["trouve"]:
        info["a_source"] = a_cle_source
        # Évaluation de la précision de la date
        est_approx = any(k in info["date"].upper() for k in ["ABT", "BEF", "AFT", "BET", "CALC", "EST"])
        mots_date = info["date"].split()
        if len(mots_date) == 1 and mots_date[0].isdigit():
            est_approx = True
        info["precision"] = "Approximative" if est_approx else "Précise"
        
    return info

def traduire_date(date_anglaise):
    """Traduit brièvement les mois pour l'affichage console."""
    mots = date_anglaise.split()
    mots_traduits = []
    for mot in mots:
        m_up = mot.upper()
        mots_traduits.append(TRADUCTION_DATES.get(m_up, mot))
    return " ".join(mots_traduits)

def est_annee_dans_fourchette(date_str, deb, fin):
    """Vérifie si l'année correspond aux critères de dates, accepte les approximations."""
    if not date_str or date_str == "Inconnue": return False
    # Extrait tous les nombres à 4 chiffres (ex: "ABT 1664" -> 1664)
    annees = [int(s) for s in re.findall(r'\b\d{4}\b', date_str)]
    if not annees: return False
    
    annee = annees[0]
    if deb and fin: return int(deb) <= annee <= int(fin)
    if deb: return annee >= int(deb)
    if fin: return annee <= int(fin)
    return True

def recuperer_ascendance_maison(id_depart, individus, fam_liste, ancetres_trouves=None):
    """Construit la liste des ID des ancêtres de manière récursive."""
    if ancetres_trouves is None:
        ancetres_trouves = set()
        
    if id_depart not in individus or id_depart in ancetres_trouves:
        return ancetres_trouves
    
    ancetres_trouves.add(id_depart)
    ind = individus[id_depart]
    
    for famc_id in ind["parents_familles"]:
        for fam in fam_liste:
            if fam["id"] == famc_id: 
                if fam["husband"]: 
                    recuperer_ascendance_maison(fam["husband"], individus, fam_liste, ancetres_trouves)
                if fam["wife"]: 
                    recuperer_ascendance_maison(fam["wife"], individus, fam_liste, ancetres_trouves)
    return ancetres_trouves

def lancer_assistant_naturel():
    individus, familles = charger_gedcom_maison(CHEMIN_GEDCOM)
    if not individus: return

    while True:
        print("\n" + "="*60)
        phrase = input("💬 Quelle liste souhaitez-vous extraire ? (ou 'quitter') :\n👉 ").strip()
        
        if phrase.lower() in ["quitter", "exit", ""]:
            print("Au revoir !")
            break
            
        print("🧠 L'IA analyse votre demande...")
        filtres = interroger_ia_pour_filtres(phrase)
        
        if not filtres or not filtres.get("EVENEMENT"):
            print("⚠️ L'IA n'a pas pu déterminer les critères. Essayez de bien spécifier l'événement.")
            continue
            
        tag_ev = filtres.get("EVENEMENT")
        commune = filtres.get("COMMUNE", "").lower() if filtres.get("COMMUNE") else None
        f_source = filtres.get("FILTRE_SOURCE")
        
        # CORRECTION : Si l'utilisateur donne une fourchette de dates, on FORCE l'inclusion des dates approximatives
        if filtres.get("ANNEE_DEBUT") or filtres.get("ANNEE_FIN"):
            f_date = "TOUT"
        else:
            f_date = filtres.get("FILTRE_DATE")
            
        ascendance_nom = filtres.get("ASCENDANCE_DE")
        
        liste_individus_cible = individus.copy()
        
        # Gestion interactive de l'ascendance (Multi-choix)
        if ascendance_nom:
            print(f"🧬 Filtrage de l'arbre pour l'ascendance de : '{ascendance_nom}'...")
            
            # Recherche de toutes les correspondances partielles dans le nom
            individus_trouves = []
            for i_id, i_obj in individus.items():
                if ascendance_nom.lower() in i_obj["nom"].lower():
                    individus_trouves.append(i_obj)
            
            id_cible = None
            
            if len(individus_trouves) == 0:
                print(f"⚠️ Aucun individu trouvé pour le nom '{ascendance_nom}'. Recherche globale.")
            elif len(individus_trouves) == 1:
                id_cible = individus_trouves[0]['id']
                print(f"   🎯 Un seul individu correspond : {individus_trouves[0]['nom']} ({id_cible})")
            else:
                # CAS MULTI-CHOIX : Menu d'homonymes interactif avec pagination et filtre interne
                debut_index = 0
                taille_page = 15
                while True:
                    print(f"\n🤔 {len(individus_trouves)} individus correspondent. Affichage des choix {debut_index + 1} à {min(debut_index + taille_page, len(individus_trouves))} :")
                    page_courante = individus_trouves[debut_index:debut_index + taille_page]
                    for idx, ind in enumerate(page_courante):
                        print(f"   [{debut_index + idx + 1}] ID: {ind['id']} | Nom: {ind['nom']}")
                    
                    print("\n💡 Options : [S] Suivants | [P] Précédents | [F] Filtrer (par prénom) | [0] Annuler")
                    choix = input(f"👉 Entrez le numéro ou une option : ").strip().upper()
                    
                    if choix == "0": 
                        print("Filtre d'ascendance annulé.")
                        break
                    elif choix == "S" and debut_index + taille_page < len(individus_trouves): 
                        debut_index += taille_page
                    elif choix == "P" and debut_index > 0: 
                        debut_index -= taille_page
                    elif choix == "F":
                        filtre_texte = input("🔍 Entrez un prénom ou mot-clé pour affiner la liste : ").strip().lower()
                        individus_trouves = [i for i in individus_trouves if filtre_texte in i["nom"].lower()]
                        debut_index = 0
                    elif choix.isdigit() and 1 <= int(choix) <= len(individus_trouves):
                        id_cible = individus_trouves[int(choix) - 1]['id']
                        break
                    else: 
                        print("Saisie invalide. Réessayez.")
            
            # Si une personne pivot unique a été sélectionnée et validée
            if id_cible:
                ids_ancetres = recuperer_ascendance_maison(id_cible, individus, familles)
                liste_individus_cible = {i_id: individus[i_id] for i_id in ids_ancetres if i_id in individus}
                print(f"   🎯 Branche verrouillée sur : {individus[id_cible]['nom']} ({id_cible})")
                print(f"   🧬 Total d'ancêtres retenus pour l'analyse : {len(liste_individus_cible)}")

        resultats = []

        # Traitement Naissances (BIRT) et Décès (DEAT)
        if tag_ev in ["BIRT", "DEAT"]:
            nom_ev = "Naissance" if tag_ev == "BIRT" else "Décès"
            for ind in liste_individus_cible.values():
                ev_info = analyser_evenement_maison(ind["lignes"], tag_ev)
                if not ev_info["trouve"]: continue
                
                if commune and commune not in ev_info["lieu"].lower(): continue
                if (filtres.get("ANNEE_DEBUT") or filtres.get("ANNEE_FIN")) and not est_annee_dans_fourchette(ev_info["date"], filtres.get("ANNEE_DEBUT"), filtres.get("ANNEE_FIN")):
                    continue
                    
                if f_source == "MANQUANTE" and ev_info["a_source"]: continue
                
                # CORRECTION : On ne bloque plus si f_date est passé à TOUT (cas des fourchettes forcées)
                if f_date == "PRECISE" and ev_info["precision"] != "Précise": continue
                
                statut_s = "🟢 Sourcé" if ev_info["a_source"] else "🔴 Manquant"
                date_fr = traduire_date(ev_info["date"])
                resultats.append([ind["id"], ind["nom"], "", nom_ev, date_fr, ev_info["precision"], ev_info["lieu"], statut_s])

        # Traitement Mariages (MARR)
        elif tag_ev == "MARR":
            for fam in familles:
                ev_info = analyser_evenement_maison(fam["lignes"], "MARR")
                if not ev_info["trouve"]: continue
                
                if commune and commune not in ev_info["lieu"].lower(): continue
                if (filtres.get("ANNEE_DEBUT") or filtres.get("ANNEE_FIN")) and not est_annee_dans_fourchette(ev_info["date"], filtres.get("ANNEE_DEBUT"), filtres.get("ANNEE_FIN")):
                    continue
                    
                if f_source == "MANQUANTE" and ev_info["a_source"]: continue
                if f_date == "PRECISE" and ev_info["precision"] != "Précise": continue
                
                nom_mari = individus.get(fam["husband"], {}).get("nom", "Inconnu") if fam["husband"] else "Inconnu"
                nom_femme = individus.get(fam["wife"], {}).get("nom", "Inconnu") if fam["wife"] else "Inconnu"
                
                if ascendance_nom and (fam["husband"] not in liste_individus_cible and fam["wife"] not in liste_individus_cible):
                    continue
                    
                statut_s = "🟢 Sourcé" if ev_info["a_source"] else "🔴 Manquant"
                date_fr = traduire_date(ev_info["date"])
                resultats.append([fam["id"], nom_mari, nom_femme, "Mariage", date_fr, ev_info["precision"], ev_info["lieu"], statut_s])

        # Affichage des résultats en console (limité aux 30 premiers)
        print("\n" + "-" * 30 + f" RÉSULTATS ({len(resultats)} correspondances à {filtres.get('COMMUNE')}) " + "-" * 30)
        for res in resultats[:30]:
            if res[3] == "Mariage":
                print(f"- 💍 {res[1]} X {res[2]} | Date: {res[4]} | Lieu: {res[6]} | Source: {res[7]}")
            else:
                print(f"- 👤 {res[1]} | {res[3]}: {res[4]} | Lieu: {res[6]} | Source: {res[7]}")
                
        if len(resultats) > 30:
            print(f"\n... et {len(resultats) - 30} autres lignes (voir le fichier Excel/CSV).")
            
        # Génération du fichier CSV/Excel de travail
        if resultats:
            nom_csv = os.path.join(DOSSIER_EXPORT, "extraction_demande.csv")
            with open(nom_csv, mode="w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["ID", "Nom / Époux", "Épouse", "Événement", "Date", "Précision", "Lieu", "Source"])
                writer.writerows(resultats)
            print(f"💾 Liste complète enregistrée dans : {nom_csv}")

if __name__ == "__main__":
    lancer_assistant_naturel()