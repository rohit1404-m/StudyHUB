from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import uuid
from functools import wraps

app = Flask(__name__)
CORS(app)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "studyhub-secret-key-change-in-production")

# =====================================================
# DATABASE CONFIG (PostgreSQL)
# =====================================================

app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://postgres:root@localhost:5432/studyhub"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# In-memory store for admin tokens (use Redis/DB in production)
admin_tokens = set()

# =====================================================
# UPLOAD FOLDER CONFIG
# =====================================================

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# =====================================================
# MODELS
# =====================================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    notes = db.relationship('Note', backref='user', lazy=True)

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(300), nullable=False)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)


class QuestionPaper(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(100), nullable=False)  # e.g. "Final Exam", "Mid Term"
    downloads = db.Column(db.Integer, default=0)
    file_url = db.Column(db.String(500), nullable=True)  # optional link or path


class TopQuestionSet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(200), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    questions = db.Column(db.JSON, nullable=False)  # list of strings


# Create tables and seed admin + initial content
with app.app_context():
    db.create_all()
    # Seed default admin (username: admin, password: 123)
    if not Admin.query.filter_by(username="admin").first():
        admin = Admin(
            username="admin",
            password=generate_password_hash("123")
        )
        db.session.add(admin)
        db.session.commit()

    # Seed question papers if empty
    if QuestionPaper.query.count() == 0:
        for p in [
            {"title": "Data Structures - Final Exam 2023", "subject": "Data Structures", "semester": 3, "year": 2023, "type": "Final Exam"},
            {"title": "Database Management - Mid Term 2023", "subject": "Database Management", "semester": 4, "year": 2023, "type": "Mid Term"},
            {"title": "Operating Systems - Final Exam 2023", "subject": "Operating Systems", "semester": 5, "year": 2023, "type": "Final Exam"},
            {"title": "Computer Networks - Final Exam 2022", "subject": "Computer Networks", "semester": 6, "year": 2022, "type": "Final Exam"},
            {"title": "Machine Learning - Mid Term 2023", "subject": "Machine Learning", "semester": 7, "year": 2023, "type": "Mid Term"},
        ]:
            db.session.add(QuestionPaper(downloads=0, **p))
        db.session.commit()

    # Seed top questions if empty
    if TopQuestionSet.query.count() == 0:
        db.session.add(TopQuestionSet(subject="Data Structures", semester=3, questions=[
            "Explain the difference between Array and Linked List with examples.",
            "What is a Binary Search Tree? Write insertion algorithm.",
            "Explain different types of tree traversals with examples.",
            "What is hashing? Explain collision resolution techniques.",
            "Write a program to implement Stack using Arrays.",
            "Explain the concept of AVL trees with rotations.",
            "What is a Graph? Explain BFS and DFS traversal.",
            "Explain the working of Quick Sort with time complexity.",
            "What is a Priority Queue? How is it implemented using Heap?",
            "Explain the concept of Dynamic Programming with examples.",
        ]))
        db.session.add(TopQuestionSet(subject="Database Management", semester=4, questions=[
            "Explain ACID properties of database transactions.",
            "What is Normalization? Explain 1NF, 2NF, 3NF with examples.",
            "Write SQL queries for JOIN operations with examples.",
            "What is indexing? Explain different types of indexes.",
            "Explain the concept of ER Diagram with notation.",
            "What is a deadlock? Explain prevention techniques.",
            "Explain the difference between DBMS and RDBMS.",
            "What are triggers and stored procedures? Give examples.",
            "Explain the concept of views in SQL.",
            "What is concurrency control? Explain different protocols.",
        ]))
        db.session.commit()

# =====================================================
# ROUTES
# =====================================================

@app.route("/api/message")
def message():
    return jsonify({"message": "Backend Running Successfully 🚀"})


# -------------------- SIGNUP --------------------

@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.json

    existing_user = User.query.filter_by(email=data["email"]).first()
    if existing_user:
        return jsonify({"message": "Email already registered"}), 400

    hashed_password = generate_password_hash(data["password"])

    new_user = User(
        username=data["username"],
        email=data["email"],
        password=hashed_password
    )

    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message": "User registered successfully ✅"})


# -------------------- LOGIN --------------------

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json

    user = User.query.filter_by(email=data["email"]).first()

    if user and check_password_hash(user.password, data["password"]):
        return jsonify({
            "message": "Login successful ✅",
            "user_id": user.id,
            "username": user.username
        })
    else:
        return jsonify({"message": "Invalid email or password ❌"}), 401

# -------------------- UPLOAD NOTE --------------------

@app.route("/api/upload", methods=["POST"])
def upload_note():
    title = request.form.get("title")
    file = request.files.get("file")
    user_id = request.form.get("user_id")

    if not file or not user_id:
        return jsonify({"message": "Missing data"}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)

    new_note = Note(
        title=title,
        filename=filename,
        user_id=user_id
    )

    db.session.add(new_note)
    db.session.commit()

    return jsonify({"message": "File uploaded successfully ✅"})



@app.route("/api/profile/<int:user_id>", methods=["GET"])
def get_profile(user_id):
    user = User.query.get(user_id)

    if not user:
        return jsonify({"message": "User not found"}), 404

    notes_count = Note.query.filter_by(user_id=user_id).count()

    return jsonify({
        "username": user.username,
        "email": user.email,
        "notes_uploaded": notes_count
    })





# @app.route("/api/profile/<int:user_id>", methods=["GET"])
# def profile(user_id):
#     user = User.query.get_or_404(user_id)

#     notes_count = Note.query.filter_by(user_id=user_id).count()

#     return jsonify({
#         "username": user.username,
#         "email": user.email,
#         "notes_uploaded": notes_count
#     })


# -------------------- GET ALL NOTES --------------------

@app.route("/api/notes", methods=["GET"])
def get_notes():
    user_id = request.args.get("user_id", type=int)
    if user_id is not None:
        notes = Note.query.filter_by(user_id=user_id).all()
    else:
        notes = Note.query.all()

    notes_list = [
        {
            "id": note.id,
            "title": note.title,
            "filename": note.filename
        }
        for note in notes
    ]

    return jsonify(notes_list)


# -------------------- DOWNLOAD --------------------

@app.route("/api/download/<filename>", methods=["GET"])
def download_note(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)


# =====================================================
# ADMIN AUTH
# =====================================================

def get_admin_token():
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    return auth[7:].strip()


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_admin_token()
        if not token or token not in admin_tokens:
            return jsonify({"message": "Admin access required"}), 401
        return f(*args, **kwargs)
    return decorated


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    admin = Admin.query.filter_by(username=username).first()
    if not admin or not check_password_hash(admin.password, password):
        return jsonify({"message": "Invalid admin credentials"}), 401

    token = str(uuid.uuid4())
    admin_tokens.add(token)
    return jsonify({"message": "Login successful", "token": token})


# =====================================================
# QUESTION PAPERS (public read, admin write)
# =====================================================

@app.route("/api/question-papers", methods=["GET"])
def list_question_papers():
    papers = QuestionPaper.query.order_by(QuestionPaper.year.desc(), QuestionPaper.id.desc()).all()
    return jsonify([
        {
            "id": p.id,
            "title": p.title,
            "subject": p.subject,
            "semester": p.semester,
            "year": p.year,
            "type": p.type,
            "downloads": p.downloads or 0,
            "file_url": p.file_url,
        }
        for p in papers
    ])


@app.route("/api/admin/question-papers", methods=["GET"])
@require_admin
def admin_list_question_papers():
    return list_question_papers()


@app.route("/api/admin/question-papers", methods=["POST"])
@require_admin
def admin_create_question_paper():
    data = request.json or {}
    title = data.get("title", "").strip()
    subject = data.get("subject", "").strip()
    semester = data.get("semester")
    year = data.get("year")
    paper_type = data.get("type", "Final Exam").strip()
    file_url = data.get("file_url", "").strip() or None

    if not title or not subject or semester is None or year is None:
        return jsonify({"message": "title, subject, semester, year required"}), 400

    paper = QuestionPaper(
        title=title,
        subject=subject,
        semester=int(semester),
        year=int(year),
        type=paper_type or "Final Exam",
        downloads=0,
        file_url=file_url,
    )
    db.session.add(paper)
    db.session.commit()
    return jsonify({
        "id": paper.id,
        "title": paper.title,
        "subject": paper.subject,
        "semester": paper.semester,
        "year": paper.year,
        "type": paper.type,
        "downloads": paper.downloads,
        "file_url": paper.file_url,
    }), 201


@app.route("/api/admin/question-papers/<int:pid>", methods=["PUT"])
@require_admin
def admin_update_question_paper(pid):
    paper = QuestionPaper.query.get(pid)
    if not paper:
        return jsonify({"message": "Not found"}), 404
    data = request.json or {}
    if "title" in data:
        paper.title = str(data["title"]).strip()
    if "subject" in data:
        paper.subject = str(data["subject"]).strip()
    if "semester" in data:
        paper.semester = int(data["semester"])
    if "year" in data:
        paper.year = int(data["year"])
    if "type" in data:
        paper.type = str(data["type"]).strip() or "Final Exam"
    if "file_url" in data:
        paper.file_url = str(data["file_url"]).strip() or None
    db.session.commit()
    return jsonify({
        "id": paper.id,
        "title": paper.title,
        "subject": paper.subject,
        "semester": paper.semester,
        "year": paper.year,
        "type": paper.type,
        "downloads": paper.downloads,
        "file_url": paper.file_url,
    })


@app.route("/api/admin/question-papers/<int:pid>", methods=["DELETE"])
@require_admin
def admin_delete_question_paper(pid):
    paper = QuestionPaper.query.get(pid)
    if not paper:
        return jsonify({"message": "Not found"}), 404
    db.session.delete(paper)
    db.session.commit()
    return jsonify({"message": "Deleted"})


# =====================================================
# TOP QUESTIONS (public read, admin write)
# =====================================================

@app.route("/api/top-questions", methods=["GET"])
def list_top_questions():
    sets = TopQuestionSet.query.order_by(TopQuestionSet.semester, TopQuestionSet.subject).all()
    return jsonify([
        {
            "id": str(s.id),
            "subject": s.subject,
            "semester": s.semester,
            "questions": s.questions if isinstance(s.questions, list) else [],
        }
        for s in sets
    ])


@app.route("/api/admin/top-questions", methods=["GET"])
@require_admin
def admin_list_top_questions():
    return list_top_questions()


@app.route("/api/admin/top-questions", methods=["POST"])
@require_admin
def admin_create_top_questions():
    data = request.json or {}
    subject = data.get("subject", "").strip()
    semester = data.get("semester")
    questions = data.get("questions")
    if not isinstance(questions, list):
        questions = []

    if not subject or semester is None:
        return jsonify({"message": "subject and semester required"}), 400

    s = TopQuestionSet(subject=subject, semester=int(semester), questions=questions)
    db.session.add(s)
    db.session.commit()
    return jsonify({
        "id": str(s.id),
        "subject": s.subject,
        "semester": s.semester,
        "questions": s.questions,
    }), 201


@app.route("/api/admin/top-questions/<int:tid>", methods=["PUT"])
@require_admin
def admin_update_top_questions(tid):
    s = TopQuestionSet.query.get(tid)
    if not s:
        return jsonify({"message": "Not found"}), 404
    data = request.json or {}
    if "subject" in data:
        s.subject = str(data["subject"]).strip()
    if "semester" in data:
        s.semester = int(data["semester"])
    if "questions" in data and isinstance(data["questions"], list):
        s.questions = data["questions"]
    db.session.commit()
    return jsonify({
        "id": str(s.id),
        "subject": s.subject,
        "semester": s.semester,
        "questions": s.questions,
    })


@app.route("/api/admin/top-questions/<int:tid>", methods=["DELETE"])
@require_admin
def admin_delete_top_questions(tid):
    s = TopQuestionSet.query.get(tid)
    if not s:
        return jsonify({"message": "Not found"}), 404
    db.session.delete(s)
    db.session.commit()
    return jsonify({"message": "Deleted"})


# =====================================================
# RUN SERVER
# =====================================================

if __name__ == "__main__":
    app.run(debug=True, port=5000)