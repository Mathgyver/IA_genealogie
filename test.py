import os
import csv
import ollama

# Configuration automatique du chemin
NOM_FICHIER = r"F:\Genealogie_IA\mon_test.ged"
DOSSIER_EXPORT = r"F:\Genealogie_IA"
MODELE_IA = "gemma2:2b" # Change par "gemma2:2b" si tu as téléchargé Gemma

# Dictionnaire de traduction des mois et mots-clés GEDCOM
TRADUCTION_DATES = {
    "JAN": "janvier", "FEB": "février", "MAR": "mars", "APR": "avril",
    "MAY": "mai", "JUN": "juin", "JUL": "juillet", "AUG": "août",
    "SEP": "septembre", "OCT": "octobre", "NOV": "novembre", "DEC": "décembre",
    "ABT": "environ", "BEF": "avant", "AFT": "après", "BET": "entre", "AND": "et"
}

def traduire_et_evaluer_date(date_anglaise):
    """Traduit la date en français et détermine si elle est précise ou approximative."""
    if not date_anglaise or date_anglaise == "Inconnue":
        return date_anglaise, "Inconnue"
        
    mots = date_anglaise.split()
    mots_traduits = []
    est_approximative = False
    
    mots_cles_approx = ["ABT", "BEF", "AFT", "BET", "CALC", "EST"]
    
    for mot in mots:
        mot_majuscule = mot.upper()
        if mot_majuscule in mots_cles_approx:
            est_approximative = True
            
        if mot_majuscule in TRADUCTION_DATES:
            mots_traduits.append(TRADUCTION_DATES[mot_majuscule])
        else:
            mots_traduits.append(mot)
            
    date_fr = " ".join(mots_traduits)
    
    if len(mots) == 1 and mots[0].isdigit():
        est_approximative = True
        
    precision = "Approximative" if est_approximative else "Précise"
    return date_fr, precision

def nettoyer_nom_heredis(ligne_name):
    """Nettoie les slashes Heredis pour un affichage propre avec espace."""
    nom_brut = ligne_name.replace("1 NAME ", "").strip()
    if "/" in nom_brut:
        nom_nettoye = nom_brut.replace("/", " ", 1).replace("/", "")
        return " ".join(nom_nettoye.split())
    return nom_brut

def charger_gedcom_complet(chemin):
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
    
    for i, ligne in enumerate(lignes):
        ligne_propre = ligne.strip()
        
        if ligne_propre.startswith("0 "):
            if bloc_courant:
                if type_bloc == "INDI":
                    dictionnaire_individus[bloc_courant["id"]] = bloc_courant
                elif type_bloc == "FAM":
                    liste_familles.append(bloc_courant)
            
            elements = ligne_propre.split(" ")
            if len(elements) >= 3:
                id_bloc = elements[1]
                tag_bloc = elements[2]
                
                if tag_bloc == "INDI":
                    type_bloc = "INDI"
                    bloc_courant = {"id": id_bloc, "nom": "Inconnu", "lignes": []}
                elif tag_bloc == "FAM":
                    type_bloc = "FAM"
                    bloc_courant = {"id": id_bloc, "lignes": []}
                else:
                    bloc_courant = None
                    type_bloc = None
            else:
                bloc_courant = None
                type_bloc = None
        
        elif bloc_courant and not ligne_propre.startswith("0 "):
            bloc_courant["lignes"].append(ligne_propre)
            if type_bloc == "INDI" and ligne_propre.startswith("1 NAME "):
                bloc_courant["nom"] = nettoyer_nom_heredis(ligne_propre)
                
    if bloc_courant:
        if type_bloc == "INDI":
            dictionnaire_individus[bloc_courant["id"]] = bloc_courant
        elif type_bloc == "FAM":
            liste_familles.append(bloc_courant)
        
    print(f"✅ {len(dictionnaire_individus)} individus et {len(liste_familles)} familles chargés.\n")
    return dictionnaire_individus, liste_familles

def analyser_evenement(lignes_bloc, tag_evenement):
    """Recherche un événement et qualifie précisément le niveau des sources rattachées."""
    info = {"trouve": False, "date": "Inconnue", "lieu": "Inconnu", "statut_source": "🔴 AUCUNE SOURCE", "details_source": ""}
    dans_evenement = False
    a_cle_source = False
    textes_sources = []
    
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
                reste = ligne.split("SOUR", 1)[1].strip()
                if reste and not reste.startswith("@"):
                    textes_sources.append(reste)
            
            elif a_cle_source and (ligne.startswith("3 TITL") or ligne.startswith("3 NOTE") or ligne.startswith("3 TEXT") or ligne.startswith("4 TEXT")):
                contenu_texte = ligne.split(" ", 2)[-1].strip()
                if contenu_texte:
                    textes_sources.append(contenu_texte)
                    
            elif ligne.startswith("1 "):
                dans_evenement = False
    
    if a_cle_source:
        textes_propres = [t.replace("@", "").strip() for t in textes_sources if t.strip()]
        if textes_propres:
            info["statut_source"] = "🟢 Source qualifiée"
            info["details_source"] = " - ".join(textes_propres[:2])
        else:
            info["statut_source"] = "🟡 Source incomplète ou brute"
            
    return info

def extraire_conjoints_famille(lignes_famille):
    """Identifie les ID du mari et de l'épouse dans un bloc famille."""
    id_epoux = None
    id_epouse = None
    for ligne in lignes_famille:
        if ligne.startswith("1 HUSB "):
            id_epoux = ligne.replace("1 HUSB ", "").strip()
        elif ligne.startswith("1 WIFE "):
            id_epouse = ligne.replace("1 WIFE ", "").strip()
    return id_epoux, id_epouse

def exporter_vers_csv(nom_commune, type_evenement, lignes_rapport):
    """Génère un fichier CSV ouvrable dans Excel contenant les résultats de la recherche."""
    nom_fich_propre = nom_commune.replace(" ", "_").replace("-", "_")
    chemin_csv = os.path.join(DOSSIER_EXPORT, f"rapport_{nom_fich_propre}_{type_evenement}.csv")
    
    entetes = ["ID GEDCOM", "Individu / Époux X", "Épouse Y (si Mariage)", "Événement", "Date", "Précision Date", "Lieu", "Statut Source", "Détails Source"]
    
    try:
        with open(chemin_csv, mode="w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(entetes)
            writer.writerows(lignes_rapport)
        print(f"💾 Fichier Excel/CSV généré avec succès : {chemin_csv}")
    except Exception as e:
        print(f"⚠️ Impossible de générer le fichier CSV : {e}")

def demander_analyse_ia(nom_commune, type_ev, actes_manquants):
    """Envoie la liste des problèmes détectés à l'IA locale pour obtenir des conseils."""
    if not actes_manquants:
        print("💡 Aucun acte manquant ou approximatif à analyser pour cette commune. Beau travail !")
        return
        
    print(f"\n🧠 Connexion à l'IA locale ({MODELE_IA}) en cours... Merci de patienter.")
    
    # Construction de la liste textuelle pour l'IA
    contexte_donnees = ""
    for act in actes_manquants[:25]: # On limite aux 25 premiers pour ne pas saturer la mémoire des petites configs
        contexte_donnees += f"- Nom: {act['nom']}, Événement: {type_ev}, Date: {act['date']} ({act['precision']}), Statut Source: {act['statut']}\n"

    # Consignes claires données à l'IA en français
    prompt = f"""
    Tu es un expert en généalogie française et en histoire des archives paroissiales et d'état civil.
    Voici une liste d'actes de {type_ev} concernant la commune de '{nom_commune}' qui posent problème dans mon arbre généalogique (soit ils n'ont pas de source valide, soit la date est une approximation brute).
    
    Données à analyser :
    {contexte_donnees}
    
    Rédige-moi une analyse rapide (en français) contenant :
    1. Des conseils stratégiques généraux sur la recherche de ces actes spécifiques dans la commune de {nom_commune} ou sa région (ex: lacunes de registres connues, structures notariales, communes limitrophes à surveiller).
    2. Identifie 2 ou 3 individus prioritaires dans cette liste pour lesquels débloquer la source permettrait de remonter une branche majeure, et explique pourquoi.
     Sois concis, clair et purement orienté vers l'aide à la recherche généalogique.
    """
    
    try:
        reponse = ollama.chat(model=MODELE_IA, messages=[
            {"role": "user", "content": prompt}
        ])
        print("\n" + "="*30 + " RECOMMANDATIONS DE L'IA " + "="*30)
        print(reponse['message']['content'])
        print("="*85 + "\n")
    except Exception as e:
        print(f"⚠️ Impossible de joindre l'IA locale : {e}")
        print("Assurez-vous qu'Ollama tourne bien en arrière-plan sur votre PC (icône près de l'horloge).\n")

def executer_assistant():
    individus, familles = charger_gedcom_complet(NOM_FICHIER)
    if not individus:
        return

    while True:
        print("--- ASSISTANT DE RECHERCHE GÉNÉALOGIQUE ---")
        saisie_utilisateur = input("👉 Entrez le nom de la COMMUNE (ou 'quitter' pour fermer) : ").strip().lower()
        
        if saisie_utilisateur == "quitter" or not saisie_utilisateur:
            print("Au revoir !")
            break
            
        commune_recherchee = saisie_utilisateur.replace("-", " ")
        
        print("\nQuel ÉVÉNEMENT souhaitez-vous analyser ?")
        print("1. Naissances (BIRT)")
        print("2. Décès (DEAT)")
        print("3. Mariages (MARR)")
        choix = input("👉 Votre choix (1, 2 ou 3) : ").strip()
        
        if choix == "1":
            tag_recherche, nom_ev = "BIRT", "Naissance"
        elif choix == "2":
            tag_recherche, nom_ev = "DEAT", "Décès"
        elif choix == "3":
            tag_recherche, nom_ev = "MARR", "Mariage"
        else:
            print("Choix invalide, retour au menu.\n")
            continue
        
        print(f"\n🔍 Analyse des {nom_ev}s pour la commune : '{saisie_utilisateur}'...\n")
        
        total_trouve = 0
        total_sans_source = 0
        total_incompletes = 0
        total_precises = 0
        total_approximatives = 0
        Donnees_pour_csv = []
        liste_problemes_ia = [] # Stockage spécifique pour l'analyse IA
        
        if tag_recherche in ["BIRT", "DEAT"]:
            for ind in individus.values():
                ev_info = analyser_evenement(ind["lignes"], tag_recherche)
                
                if ev_info["trouve"]:
                    lieu_nettoye = ev_info["lieu"].lower().replace("-", " ")
                    if commune_recherchee in lieu_nettoye:
                        total_trouve += 1
                        
                        if "🔴" in ev_info["statut_source"]:
                            total_sans_source += 1
                        elif "🟡" in ev_info["statut_source"]:
                            total_incompletes += 1
                        
                        date_fr, precision_date = traduire_et_evaluer_date(ev_info["date"])
                        
                        if precision_date == "Précise":
                            total_precises += 1
                        elif precision_date == "Approximative":
                            total_approximatives += 1
                        
                        print(f"- {ind['nom']} (ID: {ind['id']})")
                        print(f"  📅 {nom_ev} : {date_fr} ({precision_date}) à {ev_info['lieu']}")
                        texte_affichage = f"  📜 Statut : {ev_info['statut_source']}"
                        if ev_info["details_source"]:
                            texte_affichage += f" ({ev_info['details_source']})"
                        print(texte_affichage)
                        print("-" * 50)
                        
                        Donnees_pour_csv.append([ind['id'], ind['nom'], "", nom_ev, date_fr, precision_date, ev_info['lieu'], ev_info['statut_source'], ev_info['details_source']])
                        
                        # Si l'acte a un problème (pas de source ou date floue), on le signale pour l'IA
                        if "🟢" not in ev_info["statut_source"] or precision_date == "Approximative":
                            liste_problemes_ia.append({"nom": ind['nom'], "date": date_fr, "precision": precision_date, "statut": ev_info['statut_source']})
                        
        elif tag_recherche == "MARR":
            for fam in familles:
                ev_info = analyser_evenement(fam["lignes"], tag_recherche)
                
                if ev_info["trouve"]:
                    lieu_nettoye = ev_info["lieu"].lower().replace("-", " ")
                    if commune_recherchee in lieu_nettoye:
                        total_trouve += 1
                        
                        if "🔴" in ev_info["statut_source"]:
                            total_sans_source += 1
                        elif "🟡" in ev_info["statut_source"]:
                            total_incompletes += 1
                        
                        id_husb, id_wife = extraire_conjoints_famille(fam["lignes"])
                        nom_husb = individus.get(id_husb, {}).get("nom", "Inconnu") if id_husb else "Inconnu"
                        nom_wife = individus.get(id_wife, {}).get("nom", "Inconnu") if id_wife else "Inconnu"
                        
                        date_fr, precision_date = traduire_et_evaluer_date(ev_info["date"])
                        
                        if precision_date == "Précise":
                            total_precises += 1
                        elif precision_date == "Approximative":
                            total_approximatives += 1
                        
                        print(f"- 💍 X : {nom_husb}")
                        print(f"  💍 Y : {nom_wife}")
                        print(f"  📅 {nom_ev} : {date_fr} ({precision_date}) à {ev_info['lieu']}")
                        texte_affichage = f"  📜 Statut : {ev_info['statut_source']}"
                        if ev_info["details_source"]:
                            texte_affichage += f" ({ev_info['details_source']})"
                        print(texte_affichage)
                        print("-" * 50)
                        
                        Donnees_pour_csv.append([fam['id'], nom_husb, nom_wife, nom_ev, date_fr, precision_date, ev_info['lieu'], ev_info['statut_source'], ev_info['details_source']])
                        
                        if "🟢" not in ev_info["statut_source"] or precision_date == "Approximative":
                            liste_problemes_ia.append({"nom": f"{nom_husb} x {nom_wife}", "date": date_fr, "precision": precision_date, "statut": ev_info['statut_source']})
                
        print(f"\n📊 BILAN POUR '{saisie_utilisateur.upper()}' ({nom_ev}s) :")
        print(f"   • Total d'actes trouvés : {total_trouve}")
        print(f"     -- dont Dates Précises 📆 : {total_precises}")
        print(f"     -- dont Dates Approximatives ⏳ : {total_approximatives}")
        print(f"   • Actes parfaitement sourcés 🟢 : {total_trouve - total_sans_source - total_incompletes}")
        print(f"   • Actes avec source brute/incomplète 🟡 : {total_incompletes}")
        print(f"   • Actes sans aucune source 🔴 : {total_sans_source}")
        print("=" * 50)
        
        if Donnees_pour_csv:
            exporter_vers_csv(saisie_utilisateur, nom_ev, Donnees_pour_csv)
            print("=" * 50)
            
            # PROMPT INTERACTIF POUR L'IA
            reponse_ia = input(f"👉 Souhaitez-vous générer une analyse stratégique par l'IA pour {saisie_utilisateur.upper()} ? (o/n) : ").strip().lower()
            if reponse_ia == "o":
                demander_analyse_ia(saisie_utilisateur, nom_ev, liste_problemes_ia)
            print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    executer_assistant()