import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import PyPDF2
import io
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change_this_in_production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'placement_prediction.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['GUIDELINES_FOLDER'] = os.path.join(BASE_DIR, 'guidelines')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Email config (keep enabled per user's choice). Configure via environment variables.
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME'])

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GUIDELINES_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
mail = Mail(app)

# Database models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    username = db.Column(db.String(150), nullable=True)
    job_role = db.Column(db.String(150), nullable=False)
    cgpa = db.Column(db.Float, nullable=False)
    communication_skills = db.Column(db.Integer, nullable=False)
    certifications = db.Column(db.Integer, nullable=False)
    internship_status = db.Column(db.String(20), nullable=False)
    projects = db.Column(db.Integer, nullable=False, default=0)
    skills = db.Column(db.Text, nullable=True)
    predicted_percentage = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ResumeAnalysis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    job_role = db.Column(db.String(150), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    analysis_text = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# Job roles and cert requirements
JOB_ROLES = {
    'Software Engineer': {'min_certifications': 1},
    'Data Scientist': {'min_certifications': 1},
    'Web Developer': {'min_certifications': 1},
    'Data Analyst': {'min_certifications': 1},
    'DevOps Engineer': {'min_certifications': 1},
    'Machine Learning Engineer': {'min_certifications': 1},
    'Full Stack Developer': {'min_certifications': 1},
    'Backend Developer': {'min_certifications': 1},
    'Frontend Developer': {'min_certifications': 1},
    'Cybersecurity Analyst': {'min_certifications': 1}
}

# Prediction logic: requirement to reach >=75%:
# CGPA > 4, communication_skills > 2, certifications > min_certifications, internship_status == 'active'
def predict_placement(cgpa, communication_skills, certifications, internship_status, job_role, projects=0, skills=''):
    base = 50.0
    min_certs = JOB_ROLES.get(job_role, {}).get('min_certifications', 0)
    requirement_met = (cgpa > 4.0 and communication_skills > 2 and certifications > min_certs and internship_status.lower() == 'active')
    if requirement_met:
        base += 30.0
    else:
        base -= 15.0
    base += min(projects * 2, 10)
    if skills:
        skills_list = [s.strip() for s in skills.split(',') if s.strip()]
        base += min(len(skills_list) * 0.5, 5)
    base += min(certifications * 2, 10)
    predicted = max(0.0, min(100.0, base))
    return round(predicted, 2), requirement_met

# Guidelines PDF generator
def generate_guidelines_pdf(job_role, outfile):
    c = canvas.Canvas(outfile, pagesize=letter)
    w, h = letter
    c.setFont("Helvetica-Bold", 20)
    c.drawString(40, h - 50, f"Placement Guidelines — {job_role}")
    c.setFont("Helvetica", 12)
    y = h - 90
    lines = [
        "These guidelines help improve placement chances.",
        "",
        "1) Improve CGPA: aim for > 4.0 (out of 10).",
        "2) Communication: practice speaking, mock interviews, presentations.",
        "3) Certifications: complete relevant certifications and display them on your resume.",
        "4) Internships: seek internships or practical projects to build experience.",
        "5) Projects: build 3-5 meaningful projects and document them on GitHub.",
        "6) Skills: keep a concise skills list and practice problem solving.",
        "",
        "Role-specific tips:"
    ]
    if 'Data' in job_role or 'Machine' in job_role:
        lines += ["- Work on data pipelines, ML models, and Jupyter notebooks."]
    if 'Web' in job_role or 'Frontend' in job_role or 'Full Stack' in job_role:
        lines += ["- Build deployable web apps and practice UI/UX basics."]
    if 'DevOps' in job_role:
        lines += ["- Learn Docker, Kubernetes, CI/CD, cloud basics."]
    for line in lines:
        if y < 60:
            c.showPage()
            y = h - 50
            c.setFont("Helvetica", 12)
        c.drawString(40, y, line)
        y -= 18
    c.save()

# Resume text extraction
def extract_text_from_pdf(path):
    try:
        with open(path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for p in reader.pages:
                text += (p.extract_text() or "") + "\n"
            return text.strip()
    except Exception:
        return ""

# Basic resume analysis fallback
def analyze_resume_basic(text, job_role):
    keywords = {
        'Software Engineer': ['python', 'java', 'c++', 'api', 'algorithms'],
        'Data Scientist': ['data', 'machine learning', 'pandas', 'numpy', 'tensorflow', 'pytorch'],
        'Web Developer': ['html', 'css', 'javascript', 'react', 'node'],
        'Data Analyst': ['sql', 'excel', 'tableau', 'power bi', 'analytics']
    }
    role_keywords = keywords.get(job_role, [])
    text_lower = (text or "").lower()
    found = [kw for kw in role_keywords if kw in text_lower]
    pct = (len(found) / max(1, len(role_keywords))) * 100
    return f"Basic Resume Analysis for {job_role}:\nFound keywords: {', '.join(found) or 'None'}\nMatch: {pct:.1f}%\n"

# Minimal AI resume analysis wrapper (uses OpenAI if configured)
def analyze_resume_ai(text, job_role):
    ai_provider = os.environ.get('AI_PROVIDER', '').lower()
    api_key = os.environ.get('AI_API_KEY', '')
    if not ai_provider or not api_key:
        return analyze_resume_basic(text, job_role)
    try:
        if ai_provider == 'openai':
            import requests
            prompt = f"Analyze this resume for a {job_role} position and provide match percentage, strengths, weaknesses, and recommendations.\n\n{text[:3000]}"
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            data = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {"role": "system", "content": "You are a helpful career advisor."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 800
            }
            resp = requests.post(url, json=data, headers=headers, timeout=20)
            if resp.status_code == 200:
                return resp.json()['choices'][0]['message']['content']
    except Exception:
        pass
    return analyze_resume_basic(text, job_role)

# Email helper
def send_email_with_attachment(to_email, subject, body, attachment_path, attachment_name):
    try:
        msg = Message(subject, recipients=[to_email], body=body)
        with open(attachment_path, 'rb') as f:
            msg.attach(attachment_name, 'application/pdf', f.read())
        mail.send(msg)
        return True, ''
    except Exception as e:
        return False, str(e)

# Routes
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        if not email or not password:
            return render_template('register.html', error="Provide email and password")
        if User.query.filter_by(email=email).first():
            return render_template('register.html', error="Email already registered")
        user = User(email=email, password_hash=generate_password_hash(password))
        db.session.add(user); db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['user_email'] = user.email
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Invalid credentials")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', user_email=session.get('user_email', ''), job_roles=list(JOB_ROLES.keys()))

@app.route('/job-roles')
def job_roles():
    return jsonify(list(JOB_ROLES.keys()))

@app.route('/predict', methods=['POST'])
def predict():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json() or {}
    def safe_float(x):
        try: return float(x)
        except (TypeError, ValueError): return 0.0
    def safe_int(x):
        try: return int(x)
        except (TypeError, ValueError): return 0
    username = data.get('username', '') or ''
    cgpa = safe_float(data.get('cgpa'))
    communication_skills = safe_int(data.get('communication_skills'))
    certifications = safe_int(data.get('certifications'))
    internship_status = (data.get('internship_status') or 'inactive').lower()
    job_role = data.get('job_role') or list(JOB_ROLES.keys())[0]
    projects = safe_int(data.get('projects'))
    skills = data.get('skills', '') or ''
    predicted, meets = predict_placement(cgpa, communication_skills, certifications, internship_status, job_role, projects, skills)
    # Save prediction
    pred = Prediction(user_id=session['user_id'], username=username, job_role=job_role, cgpa=cgpa,
                      communication_skills=communication_skills, certifications=certifications,
                      internship_status=internship_status, projects=projects, skills=skills,
                      predicted_percentage=predicted)
    db.session.add(pred); db.session.commit()
    guidelines_url = None
    if predicted < 75:
        filename = f"guidelines_{job_role.replace(' ','_')}.pdf"
        path = os.path.join(app.config['GUIDELINES_FOLDER'], filename)
        if not os.path.exists(path):
            generate_guidelines_pdf(job_role, path)
        guidelines_url = url_for('download_guidelines', role=job_role.replace(' ', '_'))
    return jsonify({'predicted_percentage': predicted, 'meets_requirements': meets, 'guidelines_url': guidelines_url, 'job_role': job_role})

@app.route('/download-guidelines/<role>')
def download_guidelines(role):
    job_role = role.replace('_', ' ')
    filename = f"guidelines_{role}.pdf"
    path = os.path.join(app.config['GUIDELINES_FOLDER'], filename)
    if not os.path.exists(path):
        generate_guidelines_pdf(job_role, path)
    return send_file(path, as_attachment=True, download_name=f"Guidelines_{job_role}.pdf")

@app.route('/send-guidelines-email', methods=['POST'])
def send_guidelines_email():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json() or {}
    job_role = data.get('job_role', '')
    to_email = session.get('user_email')
    if not job_role or not to_email:
        return jsonify({'error': 'Missing job role or user email'}), 400
    filename = f"guidelines_{job_role.replace(' ','_')}.pdf"
    path = os.path.join(app.config['GUIDELINES_FOLDER'], filename)
    if not os.path.exists(path):
        generate_guidelines_pdf(job_role, path)
    ok, err = send_email_with_attachment(to_email, f"Placement Guidelines for {job_role}", "Find attached guidelines.", path, f"Guidelines_{job_role}.pdf")
    if not ok:
        return jsonify({'error': f'Failed to send email: {err}'}), 500
    return jsonify({'message': 'Guidelines sent to your email.'})

@app.route('/upload-resume', methods=['POST'])
def upload_resume():
    if 'user_id' not in session:
        return jsonify({'error':'Not authenticated'}), 401
    if 'resume' not in request.files:
        return jsonify({'error':'No file uploaded'}), 400
    file = request.files['resume']
    job_role = request.form.get('job_role', '')
    if file.filename == '' or not file.filename.lower().endswith('.pdf'):
        return jsonify({'error':'Please upload a PDF file'}), 400
    filename = secure_filename(f"{session['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)
    text = extract_text_from_pdf(path)
    analysis = analyze_resume_ai(text, job_role)
    ra = ResumeAnalysis(user_id=session['user_id'], job_role=job_role, filename=filename, analysis_text=analysis)
    db.session.add(ra); db.session.commit()
    return jsonify({'message':'Resume uploaded', 'analysis': analysis})

if __name__ == '__main__':
    app.run(debug=True)
