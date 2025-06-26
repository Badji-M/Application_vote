from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, make_response,send_file
import os
import pandas as pd
import secrets
from werkzeug.utils import secure_filename
from markupsafe import Markup
from io import BytesIO
from xhtml2pdf import pisa
from jinja2 import Template
from datetime import datetime
import zipfile


app = Flask(__name__)
app.secret_key = "une_clef_secrete_pour_flash"

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

data_candidats = None
data_votants = None

ADMIN_PASSWORD = "BADJI"

def is_admin():
    return session.get('is_admin', False)

def envoyer_mail(votant_email, lien_vote):
    print(f"ENVOI MAIL -> à {votant_email} : Cliquez ici pour voter -> {lien_vote}")

@app.route('/')
@app.route('/accueil')
def accueil():
    return render_template('accueil.html')

@app.route('/admin')
def admin():
    if not is_admin():
        flash("Accès réservé à l'administrateur.", "danger")
        return redirect(url_for('login_admin'))

    candidats_preview = None
    votants_preview = None
    sheet_names = None

    try:
        files = os.listdir(app.config['UPLOAD_FOLDER'])
        excel_files = [f for f in files if f.endswith('.xlsx')]
        if excel_files:
            latest_file = max(excel_files, key=lambda f: os.path.getctime(os.path.join(app.config['UPLOAD_FOLDER'], f)))
            import_path = os.path.join(app.config['UPLOAD_FOLDER'], latest_file)

            xl = pd.ExcelFile(import_path)
            sheet_names = xl.sheet_names

            if 'Candidats' in sheet_names:
                df_candidats = xl.parse('Candidats')
                candidats_preview = Markup(df_candidats.head().to_html(classes="table table-striped table-bordered table-hover", index=False))

            if 'Votants' in sheet_names:
                df_votants = xl.parse('Votants')
                votants_preview = Markup(df_votants.head().to_html(classes="table table-striped table-bordered table-hover", index=False))

    except Exception as e:
        flash(f"Impossible de charger le fichier Excel importé : {e}", "warning")

    return render_template(
        'admin.html',
        sheet_names=sheet_names,
        candidats_preview=candidats_preview,
        votants_preview=votants_preview,
        import_effectue=session.get('import_effectue', False)
    )

@app.route('/login_admin', methods=['GET', 'POST'])
def login_admin():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['is_admin'] = True
            flash("Connexion réussie.", "success")
            return redirect(url_for('admin'))
        else:
            flash("Mot de passe incorrect.", "danger")
            return redirect(url_for('login_admin'))
    return render_template('login_admin.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Déconnexion réussie.", "info")
    return redirect(url_for('accueil'))

@app.route('/upload', methods=['POST'])
def upload():
    global data_candidats, data_votants

    if not is_admin():
        flash("Accès refusé.", "danger")
        return redirect(url_for('login_admin'))

    session['import_effectue'] = False

    if 'fichier' not in request.files or request.files['fichier'].filename == '':
        flash('Aucun fichier sélectionné.', 'warning')
        return redirect(url_for('admin'))

    file = request.files['fichier']
    if file and file.filename.endswith('.xlsx'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        try:
            xl = pd.ExcelFile(filepath)
            sheet_names = xl.sheet_names

            if 'Candidats' not in sheet_names or 'Votants' not in sheet_names:
                flash("Le fichier doit contenir les feuilles 'Candidats' et 'Votants'.", "danger")
                return redirect(url_for('admin'))

            data_candidats = xl.parse('Candidats')
            
            # Traitement des images des candidats
            dossier_photo = session.get('dossier_photo', 'photos')

            if 'NomFichierPhoto' in data_candidats.columns:
                data_candidats['photo_URL'] = data_candidats['NomFichierPhoto'].apply(
                    lambda nom: f"/static/images/candidats/{dossier_photo}/{nom}"
                    if pd.notna(nom) and nom.strip() != "" else "/static/images/default.png"
                )
            else:
                data_candidats['photo_URL'] = "/static/images/default.png"


            dossier_programme = session.get('dossier_programme', 'default')

            if 'NomFichierProgramme' in data_candidats.columns:
                data_candidats['programme_URL'] = data_candidats['NomFichierProgramme'].apply(
                    lambda nom: f"/static/programmes/{dossier_programme}/{nom}"
                    if pd.notna(nom) and nom.strip() != "" else "Programme non disponible"
                )
            else:
                data_candidats['programme_URL'] = "Programme non disponible"

            data_votants = xl.parse('Votants')

            
            required_cols = {'Matricule', 'Nom', 'Prénom', 'Classe'}
            if not required_cols.issubset(data_votants.columns):
                flash("La feuille Votants doit contenir les colonnes : Matricule, Nom, Prénom, Classe.", "danger")
                return redirect(url_for('admin'))

            if 'token' not in data_votants.columns:
                data_votants['token'] = data_votants.apply(lambda _: secrets.token_urlsafe(16), axis=1)

            if 'A_vote' not in data_votants.columns:
                data_votants['A_vote'] = False

            os.makedirs("data", exist_ok=True)
            data_votants.to_excel("data/liste_votants.xlsx", index=False)

            session['import_effectue'] = True
            flash("Import réussi et tokens générés.", "success")
            return redirect(url_for('admin'))

        except Exception as e:
            flash(f"Erreur lors de la lecture du fichier : {e}", "danger")
            return redirect(url_for('admin'))

    else:
        flash("Format de fichier incorrect. Seuls les fichiers .xlsx sont acceptés.", "warning")
        return redirect(url_for('admin'))



#___________Upload les photos des candidats format zip_______

@app.route('/upload_photos', methods=['POST'])
def upload_photos():
    if not is_admin():
        flash("Accès refusé.", "danger")
        return redirect(url_for('login_admin'))

    if 'photos_zip' not in request.files:
        flash("Aucun fichier ZIP sélectionné.", "warning")
        return redirect(url_for('admin'))

    file = request.files['photos_zip']

    if file.filename == '':
        flash("Aucun fichier sélectionné.", "warning")
        return redirect(url_for('admin'))

    if file and file.filename.endswith('.zip'):
        filename = secure_filename(file.filename)
        zip_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(zip_path)

        # Extraire le nom du dossier à partir du nom du fichier ZIP, ex: photos_2025.zip → photos_2025
        dossier_photo = filename.replace('.zip', '')

        extract_path = os.path.join('static', 'images', 'candidats')
        os.makedirs(extract_path, exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_path)
            
            #  Sauvegarder le nom du dossier dans la session
            session['dossier_photo'] = dossier_photo

            flash(f"Photos extraites dans le dossier : {dossier_photo}", "success")
        except zipfile.BadZipFile:
            flash("Le fichier ZIP est corrompu ou invalide.", "danger")
        finally:
            os.remove(zip_path)

        return redirect(url_for('admin'))

    else:
        flash("Veuillez uploader un fichier ZIP valide.", "warning")
        return redirect(url_for('admin'))



#___________Upload programme des candidats format zip_______

@app.route('/upload_programmes_zip', methods=['POST'])
def upload_programmes_zip():
    if not is_admin():
        flash("Accès refusé.", "danger")
        return redirect(url_for('login_admin'))

    if 'fichier_zip' not in request.files:
        flash("Aucun fichier ZIP sélectionné.", "warning")
        return redirect(url_for('admin'))

    file = request.files['fichier_zip']

    if file.filename == '':
        flash("Aucun fichier sélectionné.", "warning")
        return redirect(url_for('admin'))

    if file and file.filename.endswith('.zip'):
        filename = secure_filename(file.filename)
        zip_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(zip_path)

        # Extraire le nom du dossier à partir du nom du fichier ZIP, ex: programmes_2025.zip → programmes_2025
        dossier_programme = filename.replace('.zip', '')

        extract_path = os.path.join('static', 'programmes')
        os.makedirs(extract_path, exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(os.path.join(extract_path))

            # Sauvegarder le nom du dossier dans la session
            session['dossier_programme'] = dossier_programme

            flash(f"Programmes extraits dans le dossier : {dossier_programme}", "success")
        except zipfile.BadZipFile:
            flash("Le fichier ZIP est corrompu ou invalide.", "danger")
        finally:
            os.remove(zip_path)

        return redirect(url_for('admin'))

    else:
        flash("Veuillez uploader un fichier ZIP valide.", "warning")
        return redirect(url_for('admin'))

@app.route('/apropos')
def apropos():
    return render_template('apropos.html')

# ____________Telechager les token______________

@app.route('/telecharger_tokens')
def telecharger_tokens():
    path = os.path.join('data', 'liste_votants.xlsx')
    if os.path.exists(path):
        return send_file(path, as_attachment=True)
    else:
        flash("Le fichier de tokens n'est pas disponible. Merci d'importer les votants.", "warning")
        return redirect(url_for('admin'))

@app.route('/club')
def club():
    global data_candidats

    if data_candidats is None:
        flash("Les données des candidats ne sont pas disponibles.", "danger")
        return redirect(url_for('login_admin'))

    # L'utilisateur n'a pas encore saisi son token ? Rediriger vers /saisir_token
    if 'votant_token' not in session:
        flash("Veuillez vous identifier avec votre token pour voter.", "info")
        return redirect(url_for('saisir_token'))


    # Grouper les candidats par poste
    grouped_candidats = {}
    for _, row in data_candidats.iterrows():
        poste = row['Titre_Poste']
        grouped_candidats.setdefault(poste, []).append(row.to_dict())

    return render_template('club.html', candidats_grouped=grouped_candidats)

@app.route('/saisir_token', methods=['GET', 'POST'])
def saisir_token():
    global data_votants

    if data_votants is None:
        flash("Les données des votants ne sont pas encore importées.", "danger")
        return redirect(url_for('accueil'))

    if request.method == 'POST':
        token_saisi = request.form.get('token')
        if token_saisi in data_votants['token'].values:
            votant_info = data_votants[data_votants['token'] == token_saisi].iloc[0]
            nom = votant_info['Nom']
            prenom = votant_info['Prénom']
            session['votant_token'] = token_saisi
            flash(f"Bienvenue {prenom} {nom} ! Token validé. Vous pouvez voter maintenant.", "success")
            return redirect(url_for('club'))
            
        else:
            flash("Token invalide. Veuillez réessayer.", "danger")

    return render_template('saisir_token.html')



vote_file = 'data/votes.xlsx'

if not os.path.exists(vote_file):
    df_init = pd.DataFrame(columns=['Matricule', 'Nom_Candidat', 'Prenom_Candidat', 'ID_Poste'])
    df_init.to_excel(vote_file, index=False)

@app.route('/voter', methods=['POST'])
def voter():
    global data_votants

    if 'votant_token' not in session:
        flash("Token requis pour voter.", "danger")
        return redirect(url_for('club'))

    token = session['votant_token']
    id_poste = request.form.get('ID_Poste')
    nom = request.form.get('Nom_Candidat')
    prenom = request.form.get('Prenom_Candidat')

    if data_votants is None:
        flash("Données non chargées.", "danger")
        return redirect(url_for('club'))

    votant = data_votants[data_votants['token'] == token]
    if votant.empty:
        flash("Token invalide.", "danger")
        return redirect(url_for('club'))

    matricule = votant.iloc[0]['Matricule']

    df_votes = pd.read_excel(vote_file)
    deja_vote = df_votes[(df_votes['Matricule'] == matricule) & (df_votes['ID_Poste'] == id_poste)]
    # Récupérer la classe du votant
    classe = votant.iloc[0]['Classe']
    titre_poste = data_candidats.loc[data_candidats['ID_Poste'] == id_poste, 'Titre_Poste'].values[0]


    if not deja_vote.empty:
        flash("Vous avez déjà voté pour ce poste.", "warning")
        return redirect(url_for('club'))

    nouveau_vote = pd.DataFrame([{
    'Matricule': matricule,
    'Classe': classe,
    'ID_Poste': id_poste,
    'Titre_Poste': titre_poste,
    'Nom_Candidat': nom,
    'Prenom_Candidat': prenom
}])

    df_votes = pd.concat([df_votes, nouveau_vote], ignore_index=True)
    df_votes.to_excel(vote_file, index=False)

    flash(f"Vote enregistré pour {prenom} {nom}.", "success")
    return redirect(url_for('club'))

@app.route('/resultats')
def resultats():
    if not os.path.exists(vote_file):
        flash("Aucun vote trouvé.", "info")
        return redirect(url_for('club'))

    df_votes = pd.read_excel(vote_file)

    required_cols = {'Titre_Poste', 'Nom_Candidat', 'Prenom_Candidat', 'Matricule'}
    if not required_cols.issubset(df_votes.columns):
        flash("Le fichier de votes ne contient pas toutes les colonnes requises.", "danger")
        return redirect(url_for('club'))

    # Résultats détaillés
    resultats = (
        df_votes.groupby(['Titre_Poste', 'Nom_Candidat', 'Prenom_Candidat'])
        .size()
        .reset_index(name='Nombre_de_votes')
        .sort_values(by=['Titre_Poste', 'Nombre_de_votes'], ascending=[True, False])
    )

    # Total général de votes
    total_votes = len(df_votes)

    # Nombre de votants uniques (distincts)
    nb_votants_uniques = df_votes['Matricule'].nunique()

    # Nombre total de votants inscrits
    try:
        df_votants = pd.read_excel("data/liste_votants.xlsx")
        total_votants = len(df_votants)
    except:
        df_votants = pd.DataFrame()
        total_votants = 0

    # Taux de participation général
    taux_participation = round((nb_votants_uniques / total_votants) * 100, 2) if total_votants else 0

    # --- Taux de participation par classe ---
    if not df_votants.empty and 'Classe' in df_votants.columns:
        total_par_classe = df_votants['Classe'].value_counts().sort_index()

        # On fusionne les matricules ayant voté avec leurs classes
        votants_ayant_vote = df_votes[['Matricule']].drop_duplicates().merge(
            df_votants[['Matricule', 'Classe']], on='Matricule', how='left'
        )
        votes_par_classe = votants_ayant_vote['Classe'].value_counts().sort_index()

        taux_par_classe = pd.DataFrame({
            'Classe': total_par_classe.index,
            'Inscrits': total_par_classe.values,
            'Ont_voté': [votes_par_classe.get(cl, 0) for cl in total_par_classe.index],
        })
        taux_par_classe['Taux_participation'] = round(
            100 * taux_par_classe['Ont_voté'] / taux_par_classe['Inscrits'], 2
        )
    else:
        taux_par_classe = pd.DataFrame(columns=['Classe', 'Inscrits', 'Ont_voté', 'Taux_participation'])

    # --- Rendu du template ---
    return render_template(
        'resultats_club.html',
        resultats=resultats,
        total_votes=total_votes,
        total_votants=total_votants,
        nb_votants_uniques=nb_votants_uniques,
        taux_participation=taux_participation,
        taux_par_classe=taux_par_classe.to_dict(orient='records')  # <== À AJOUTER ICI
    )


@app.route('/redirect_admin')
def redirect_admin():
    if is_admin():
        return redirect(url_for('admin'))
    return redirect(url_for('accueil'))


@app.route('/generer_pdf', methods=['POST'])
def generer_pdf():
    if not is_admin():
        flash("Accès réservé à l'administrateur pour cette action.", "danger")
        return redirect(url_for('resultats'))

    try:
        df_votes = pd.read_excel(vote_file)
        df_votants = pd.read_excel("data/liste_votants.xlsx")
    except:
        flash("Impossible de générer le PDF, données manquantes.", "danger")
        return redirect(url_for('resultats'))

    total_votes = len(df_votes)
    nb_votants_uniques = df_votes['Matricule'].nunique()
    total_votants = len(df_votants)
    taux_participation = round((nb_votants_uniques / total_votants) * 100, 2) if total_votants else 0

    resultats = (
        df_votes.groupby(['Titre_Poste', 'Nom_Candidat', 'Prenom_Candidat'])
        .size()
        .reset_index(name='Nombre_de_votes')
        .sort_values(by=['Titre_Poste', 'Nombre_de_votes'], ascending=[True, False])
    )

    logo_path = os.path.join("static","images","logo_ensae.png")  # À adapter si tu changes le nom ou l’emplacement

    # --- TEMPLATE HTML AVANCÉ ---
    template_html = """
    <html>
    <head>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 30px;
                color: #333;
            }
            .header {
                display: flex;
                align-items: center;
                border-bottom: 2px solid #444;
                padding-bottom: 10px;
                margin-bottom: 30px;
            }
            .header img {
                height: 80px;
                margin-right: 20px;
            }
            h1 {
                font-size: 24px;
                margin: 0;
            }
            .section-title {
                background-color: #f2f2f2;
                padding: 10px;
                font-size: 18px;
                margin-top: 30px;
                border-left: 5px solid #007bff;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
            }
            th, td {
                border: 1px solid #999;
                padding: 6px 8px;
                text-align: left;
            }
            th {
                background-color: #007bff;
                color: white;
            }
            .footer {
                margin-top: 50px;
                font-size: 12px;
                text-align: center;
                color: #777;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <img src="{{ logo_path }}" alt="Logo">
            <div>
                <h1>Rapport des résultats de vote</h1>
                <p>Date de génération : {{ date }}</p>
            </div>
        </div>

        <div class="section-title">Statistiques générales</div>
        <ul>
            <li><strong>Nombre total d'inscrits :</strong> {{ total_votants }}</li>
            <li><strong>Nombre de votants uniques :</strong> {{ nb_votants_uniques }}</li>
            <li><strong>Nombre total de votes exprimés :</strong> {{ total_votes }}</li>
            <li><strong>Taux de participation :</strong> {{ taux_participation }} %</li>
        </ul>

        {% for poste, groupe in resultats.groupby('Titre_Poste') %}
            <div class="section-title">Poste : {{ poste }}</div>
            <table>
                <tr>
                    <th>Nom</th>
                    <th>Prénom</th>
                    <th>Nombre de votes</th>
                </tr>
                {% for row in groupe.itertuples() %}
                <tr>
                    <td>{{ row.Nom_Candidat }}</td>
                    <td>{{ row.Prenom_Candidat }}</td>
                    <td>{{ row.Nombre_de_votes }}</td>
                </tr>
                {% endfor %}
            </table>
        {% endfor %}

        <div class="footer">
            Rapport généré automatiquement - {{ date }}
        </div>
    </body>
    </html>
    """

    template = Template(template_html)

    html = template.render(
        total_votants=total_votants,
        nb_votants_uniques=nb_votants_uniques,
        total_votes=total_votes,
        taux_participation=taux_participation,
        resultats=resultats,
        logo_path=logo_path,
        date=datetime.now().strftime('%d/%m/%Y à %Hh%M')
    )

   

    # Générer PDF
    result = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=result, link_callback=lambda uri, rel: uri)
    if pisa_status.err:
        flash("Erreur lors de la génération du PDF.", "danger")
        return redirect(url_for('resultats'))

    result.seek(0)
    return send_file(result, mimetype='application/pdf', as_attachment=True, download_name='rapport_votes.pdf')

    


if __name__ == "__main__":
    app.run(debug=True, port=5001)
