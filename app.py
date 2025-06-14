from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
import os
import pandas as pd
import secrets
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "une_clef_secrete_pour_flash"

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

data_bureau = None
data_clubs = None
data_votants = None  # Pour stocker la base votants avec tokens

# Mot de passe admin en dur
ADMIN_PASSWORD = "admin123"

# -------- FONCTION UTILE --------
def is_admin():
    return session.get('is_admin', False)

# Fonction pour simuler l'envoi de mail (à remplacer par un vrai SMTP)
def envoyer_mail(votant_email, lien_vote):
    print(f"ENVOI MAIL -> à {votant_email} : Cliquez ici pour voter -> {lien_vote}")

# -------- PAGE D'ACCUEIL --------
@app.route('/')
@app.route('/accueil')
def accueil():
    return render_template('accueil.html')

# -------- PAGE ADMIN --------
@app.route('/admin')
def admin():
    if not is_admin():
        flash("Accès réservé à l'administrateur.", "danger")
        return redirect(url_for('login_admin'))
    return render_template('admin.html')

# -------- LOGIN ADMIN - FORMULAIRE --------
@app.route('/login_admin', methods=['GET', 'POST'])
def login_admin():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['is_admin'] = True
            flash("Connexion en tant qu'administrateur réussie.", "success")
            return redirect(url_for('admin'))
        else:
            flash("Mot de passe incorrect.", "danger")
            return redirect(url_for('login_admin'))
    return render_template('login_admin.html')

# -------- LOGOUT --------
@app.route('/logout')
def logout():
    session.clear()
    flash("Déconnexion réussie.", "info")
    return redirect(url_for('accueil'))

# -------- UPLOAD DE FICHIER --------
@app.route('/upload', methods=['POST'])
def upload():
    global data_bureau, data_clubs, data_votants

    if not is_admin():
        flash("Accès refusé. Vous devez être connecté en tant qu'administrateur.", "danger")
        return redirect(url_for('login_admin'))

    if 'fichier' not in request.files:
        flash('Aucun fichier envoyé.', 'warning')
        return redirect(url_for('admin'))

    file = request.files['fichier']
    if file.filename == '':
        flash('Aucun fichier sélectionné.', 'warning')
        return redirect(url_for('admin'))

    if file and file.filename.endswith('.xlsx'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        try:
            xl = pd.ExcelFile(filepath)
            sheet_names = xl.sheet_names

            if len(sheet_names) < 2 or 'Votants' not in sheet_names:
                flash("Le fichier doit contenir au moins deux feuilles pour le bureau et les clubs, et une feuille nommée 'Votants'.", "danger")
                return redirect(url_for('admin'))

            # Lecture des feuilles
            data_bureau = xl.parse(sheet_names[0])
            data_clubs = xl.parse(sheet_names[1])
            data_votants = xl.parse('Votants')

            # Générer des tokens
            data_votants['token'] = data_votants.apply(lambda row: secrets.token_urlsafe(16), axis=1)

            # Envoi des mails
            for _, row in data_votants.iterrows():
                email = row.get('Email')
                if pd.notna(email):
                    lien_vote = url_for('vote_avec_token', token=row['token'], _external=True)
                    envoyer_mail(email, lien_vote)
                else:
                    print(f"Pas d'email pour ce votant: {row}")

            # Aperçu des feuilles (5 premières lignes)
            preview_data = {}
            for name in sheet_names:
                df = xl.parse(name)
                preview_data[name] = df.head().to_html(classes="table table-bordered table-sm", index=False)

            session['preview_data'] = preview_data
            session['sheet_names'] = sheet_names

            flash('Fichier importé avec succès, tokens générés et mails envoyés.', 'success')
            return redirect(url_for('admin'))

        except Exception as e:
            flash(f"Erreur lors de la lecture du fichier Excel: {e}", "danger")
            return redirect(url_for('admin'))
    else:
        flash('Veuillez uploader un fichier Excel (.xlsx).', 'warning')
        return redirect(url_for('admin'))


# -------- VOTE AVEC TOKEN --------
@app.route('/vote/<token>', methods=['GET', 'POST'])
def vote_avec_token(token):
    global data_bureau, data_clubs, data_votants

    if data_votants is None:
        flash("Aucune donnée de votants disponible, veuillez contacter l'administrateur.", "danger")
        return redirect(url_for('accueil'))

    # Chercher votant par token
    votant = data_votants[data_votants['token'] == token]
    if votant.empty:
        abort(404, description="Token invalide ou expiré.")

    votant = votant.iloc[0]

    # Tu peux stocker en session le token pour empêcher double vote si tu veux
    if request.method == 'POST':
        # Ici tu traites le vote envoyé par le votant (par exemple formulaire sur /vote/<token>)
        # Pour simplifier, juste un message flash
        flash(f"Vote enregistré pour {votant['Nom']} {votant['Prenom']}. Merci de votre participation !", "success")
        # Tu peux ici aussi marquer dans data_votants que ce votant a voté (à gérer selon ta logique)
        return redirect(url_for('accueil'))

    # Afficher la page de vote avec les candidats (présidentielle ou clubs)
    # Par exemple, on affiche la page présidentielle
    if data_bureau is None:
        flash('Aucune donnée du bureau AES disponible. Veuillez importer un fichier Excel.', 'warning')
        return redirect(url_for('accueil'))

    grouped_bureau = {}
    for _, row in data_bureau.iterrows():
        poste = row['Titre_Poste']
        candidat = {
            'ID_Poste': row['ID_Poste'],
            'Titre_Poste': poste,
            'Nom_Candidat': row['Nom_Candidat'],
            'Prenom_Candidat': row['Prenom_Candidat'],
            'Photo_URL': row['Photo_URL'],
            'Programme': row['Programme']
        }
        grouped_bureau.setdefault(poste, []).append(candidat)

    return render_template('club.html', bureau_grouped=grouped_bureau, votant=votant)

# -------- PRÉSIDENTIELLE (sans token, juste pour admin) --------
@app.route('/presidentielle')
def presidentielle():
    global data_bureau

    if data_bureau is None:
        flash('Aucune donnée du bureau AES disponible. Veuillez importer un fichier Excel.', 'warning')
        return redirect(url_for('admin'))

    grouped_bureau = {}
    for _, row in data_bureau.iterrows():
        poste = row['Titre_Poste']
        candidat = {
            'ID_Poste': row['ID_Poste'],
            'Titre_Poste': poste,
            'Nom_Candidat': row['Nom_Candidat'],
            'Prenom_Candidat': row['Prenom_Candidat'],
            'Photo_URL': row['Photo_URL'],
            'Programme': row['Programme']
        }
        grouped_bureau.setdefault(poste, []).append(candidat)

    return render_template('presidentielle.html', bureau_grouped=grouped_bureau)

# -------- CLUB --------
@app.route('/club')
def club():
    global data_clubs

    if data_clubs is None:
        flash('Aucune donnée des clubs disponible. Veuillez importer un fichier Excel.', 'warning')
        return redirect(url_for('admin'))

    grouped_clubs = {}
    for _, row in data_clubs.iterrows():
        poste = row['Titre_Poste']
        candidat = {
            'ID_Poste': row['ID_Poste'],
            'Titre_Poste': poste,
            'Nom_Candidat': row['Nom_Candidat'],
            'Prenom_Candidat': row['Prenom_Candidat'],
            'Photo_URL': row['Photo_URL'],
            'Programme': row['Programme']
        }
        grouped_clubs.setdefault(poste, []).append(candidat)

    return render_template('club.html', clubs_grouped=grouped_clubs)

# -------- VOTE PRÉSIDENTIEL --------
@app.route('/voter_president', methods=['POST'])
def voter_president():
    id_poste = request.form['ID_Poste']
    nom = request.form['Nom_Candidat']
    prenom = request.form['Prenom_Candidat']

    flash(f"Votre vote pour {prenom} {nom} au poste {id_poste} a été enregistré.", 'success')
    return redirect(url_for('presidentielle'))

# -------- VOTE CLUB --------
@app.route('/voter_club', methods=['POST'])
def voter_club():
    nom = request.form.get('Nom_Candidat', 'Inconnu')
    prenom = request.form.get('Prenom_Candidat', 'Inconnu')
    poste = request.form.get('ID_Poste', 'Inconnu')

    flash(f"Votre vote pour {prenom} {nom} au poste {poste} a été enregistré.", 'success')
    return redirect(url_for('club'))

# -------- REDIRECTION VERS PAGE ADMIN APRÈS LOGIN --------
@app.route('/redirect_admin')
def redirect_admin():
    if is_admin():
        return redirect(url_for('admin'))
    return redirect(url_for('accueil'))

# -------- MAIN --------
if __name__ == "__main__":
    app.run(debug=True, port=5001)
