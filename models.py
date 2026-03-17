from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    picks = db.relationship("Pick", backref="user", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Team(db.Model):
    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    seed = db.Column(db.Integer, nullable=False)
    region = db.Column(db.String(20), nullable=False)
    is_first_four = db.Column(db.Boolean, default=False)
    first_four_group = db.Column(db.String(40), nullable=True)


class Pick(db.Model):
    __tablename__ = "picks"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    game_slot = db.Column(db.String(40), nullable=False)
    picked_team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False)
    phase = db.Column(db.Integer, nullable=False)

    picked_team = db.relationship("Team")

    __table_args__ = (
        db.UniqueConstraint("user_id", "game_slot", name="uq_user_game_slot"),
    )


class GameResult(db.Model):
    __tablename__ = "game_results"

    id = db.Column(db.Integer, primary_key=True)
    game_slot = db.Column(db.String(40), unique=True, nullable=False)
    team1_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False)
    team1_seed = db.Column(db.Integer, nullable=False)
    team2_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False)
    team2_seed = db.Column(db.Integer, nullable=False)
    winner_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=True)
    round_number = db.Column(db.Integer, nullable=False)
    score_team1 = db.Column(db.Integer, nullable=True)
    score_team2 = db.Column(db.Integer, nullable=True)

    team1 = db.relationship("Team", foreign_keys=[team1_id])
    team2 = db.relationship("Team", foreign_keys=[team2_id])
    winner = db.relationship("Team", foreign_keys=[winner_id])
