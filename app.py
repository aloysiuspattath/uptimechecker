from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
import requests
import datetime
from flask_apscheduler import APScheduler
from apscheduler.schedulers.base import STATE_RUNNING

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sites.db'
app.config['SCHEDULER_API_ENABLED'] = True
db = SQLAlchemy(app)
socketio = SocketIO(app)
scheduler = APScheduler()

class Website(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(50), default='Unknown')

class UptimeRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    website_id = db.Column(db.Integer, db.ForeignKey('website.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)

with app.app_context():
    db.create_all()

# Default checking interval (in seconds)
checking_interval = 10

def check_websites():
    with app.app_context():
        websites = Website.query.all()

        for website in websites:
            try:
                response = requests.get(website.url)
                if response.status_code == 200:
                    website.status = 'Live'
                    uptime_record = UptimeRecord(website_id=website.id, timestamp=datetime.datetime.now())
                    db.session.add(uptime_record)
                else:
                    website.status = f'Down (Status Code: {response.status_code})'
            except requests.ConnectionError:
                website.status = 'Down'
                pass

        db.session.commit()
        socketio.emit('update_status', {'websites': get_websites()}, namespace='/')

def get_websites():
    return [{'name': website.name, 'url': website.url, 'status': website.status} for website in Website.query.all()]

def configure_scheduler():
    global checking_interval

    # Check if the scheduler is running before attempting to start it
    if scheduler.state != STATE_RUNNING:
        scheduler.start()

    # Remove all existing jobs before adding the new one
    scheduler.remove_all_jobs()

    # Add the job with the updated interval
    scheduler.add_job(id='check_websites', func=check_websites, trigger='interval', seconds=checking_interval)

@app.route('/')
def home():
    return render_template('index.html', checking_interval=checking_interval)

@app.route('/set_interval', methods=['POST'])
def set_interval():
    global checking_interval
    checking_interval = int(request.form.get('interval'))

    # Update the scheduler with the new interval
    configure_scheduler()

    return redirect(url_for('home'))

@app.route('/add_website', methods=['POST'])
def add_website():
    url = request.form.get('url')
    name = request.form.get('name')

    new_website = Website(url=url, name=name)
    db.session.add(new_website)
    db.session.commit()

    # Emit an event to notify the frontend about the new website
    socketio.emit('new_website_added', {'name': name, 'url': url, 'status': 'Unknown'}, namespace='/')

    return redirect(url_for('home'))

# ... (rest of the routes)

@socketio.on('connect', namespace='/')
def handle_connect():
    emit('update_status', {'websites': get_websites()})

@socketio.on('update_status_request', namespace='/')
def handle_update_status_request(message):
    emit('update_status', {'websites': get_websites()})

@socketio.on('remove_website', namespace='/')
def handle_remove_website(data):
    website_name = data['name']
    website = Website.query.filter_by(name=website_name).first()

    if website:
        db.session.delete(website)
        db.session.commit()
        socketio.emit('update_status', {'websites': get_websites()}, namespace='/')

if __name__ == '__main__':
    configure_scheduler()
    socketio.run(app, debug=True, use_reloader=False)
