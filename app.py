from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, timedelta
import pywhatkit
import time

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///clinic_pro.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'super_secret_key'

db = SQLAlchemy(app)

# ==========================================
#  DATABASE MODELS
# ==========================================

class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(10))
    address = db.Column(db.Text)
    family_history = db.Column(db.Text)
    
    # Flag to ensure Welcome Msg is sent only once
    welcome_sent = db.Column(db.Boolean, default=False)
    
    visits = db.relationship('Visit', backref='patient', lazy=True)

class Visit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    
    visit_date = db.Column(db.String(10), nullable=False)
    next_appt_date = db.Column(db.String(10))
    
    diagnosis = db.Column(db.String(200))
    procedure = db.Column(db.String(200))
    complaint = db.Column(db.Text)
    investigation = db.Column(db.Text)
    medicine_box = db.Column(db.Text)
    advice = db.Column(db.Text)
    next_plan = db.Column(db.Text)
    
    status = db.Column(db.String(20), default='Pending')
    reminder_sent = db.Column(db.Boolean, default=False)

with app.app_context():
    db.create_all()

# ==========================================
#  PAGE 1: REGISTRATION & CHECKUP
# ==========================================

@app.route('/', methods=['GET', 'POST'])
def registration_page():
    found_patient = None
    patient_history = []
    candidates = [] # List for multiple patients with same name

    # 1. HANDLE SELECTION FROM LIST (When user clicks "Select")
    selected_id = request.args.get('select_id')
    if selected_id:
        found_patient = Patient.query.get(selected_id)
        if found_patient:
            # Load history (Newest first)
            patient_history = Visit.query.filter_by(patient_id=found_patient.id).order_by(Visit.id.desc()).all()

    # 2. HANDLE SEARCH BUTTON CLICK
    if request.method == 'POST' and 'btn_search' in request.form:
        search_name = request.form.get('search_name').strip()
        
        if search_name:
            # Search by Name (Case insensitive partial match)
            results = Patient.query.filter(Patient.name.ilike(f"%{search_name}%")).all()
            
            if len(results) == 1:
                # Only 1 found? Load directly
                found_patient = results[0]
                patient_history = Visit.query.filter_by(patient_id=found_patient.id).order_by(Visit.id.desc()).all()
            elif len(results) > 1:
                # Multiple found? Show list
                candidates = results
            else:
                pass # None found

    return render_template('registration.html', patient=found_patient, history=patient_history, candidates=candidates)

@app.route('/add', methods=['POST'])
def add_patient():
    # --- 1. COLLECT DATA ---
    phone = request.form['phone']
    name = request.form['name']
    age = request.form.get('age')
    gender = request.form.get('gender')
    address = request.form.get('address')
    fam_hist = request.form.get('family_history')

    # Current Visit Data
    complaint = request.form.get('complaint')
    diagnosis = request.form.get('diagnosis')
    procedure = request.form.get('procedure')
    investigation = request.form.get('investigation')
    medicines = request.form.get('medicine_box') # This is the NEW medicine
    advice = request.form.get('advice')
    next_plan = request.form.get('next_plan')
    next_appt_date = request.form.get('next_appt_date') 

    today_str = date.today().strftime('%Y-%m-%d')
    is_new_patient = False

    # --- 2. CHECK IF PATIENT EXISTS (By Phone) ---
    existing_patient = Patient.query.filter_by(phone=phone).first()

    if existing_patient:
        # Update Old Patient Details
        existing_patient.name = name 
        existing_patient.age = age
        existing_patient.address = address
        existing_patient.family_history = fam_hist
        patient_id = existing_patient.id
    else:
        # Create New Patient
        new_patient = Patient(name=name, phone=phone, age=age, gender=gender, address=address, family_history=fam_hist)
        db.session.add(new_patient)
        db.session.commit()
        patient_id = new_patient.id
        is_new_patient = True

    # --- 3. CREATE NEW VISIT RECORD ---
    new_visit = Visit(
        patient_id=patient_id,
        visit_date=today_str,
        next_appt_date=next_appt_date,
        diagnosis=diagnosis,
        procedure=procedure,
        complaint=complaint,
        investigation=investigation,
        medicine_box=medicines,
        advice=advice,
        next_plan=next_plan,
        status='Pending',
        reminder_sent=False 
    )
    db.session.add(new_visit)
    db.session.commit()
    
    # Show welcome button ONLY if it's a truly new patient
    show_welcome = is_new_patient
    return redirect(url_for('appointments_page', new_id=patient_id if show_welcome else None))

# ==========================================
#  PAGE 2: APPOINTMENT LIST
# ==========================================

@app.route('/appointments', methods=['GET', 'POST'])
def appointments_page():
    visits = []
    
    # Handle New Patient Alert
    new_patient_id = request.args.get('new_id')
    new_patient = None
    if new_patient_id:
        new_patient = Patient.query.get(new_patient_id)
        if new_patient and new_patient.welcome_sent:
            new_patient = None

    search_date = request.form.get('search_date')
    search_treatment = request.form.get('search_treatment')
    query = Visit.query

    if request.method == 'POST':
        # --- LOGIC CHANGE FOR 'SHOW ALL' (Combine Medicines) ---
        if 'show_all' in request.form:
            # 1. Saare Patients le aao
            all_patients = Patient.query.all()
            
            for p in all_patients:
                # 2. Har patient ki saari visits nikalo (Newest First)
                p_visits = Visit.query.filter_by(patient_id=p.id).order_by(Visit.id.desc()).all()
                
                if p_visits:
                    # Sabse latest visit (Jo main row banegi)
                    latest_visit = p_visits[0]
                    
                    # 3. Saari purani aur nayi medicines ko jodna (Combine Logic)
                    combined_meds = []
                    for v in p_visits:
                        if v.medicine_box and v.medicine_box.strip():
                            # Format: [Date] Medicine Name
                            entry = f"📅 {v.visit_date}:\n{v.medicine_box}"
                            combined_meds.append(entry)
                    
                    # 4. Latest visit ke medicine box mein poora history daal do (Sirf display ke liye)
                    # "---" se separate karenge taaki saaf dikhe
                    latest_visit.medicine_box = "\n\n--------------------\n".join(combined_meds)
                    
                    # List mein add karo
                    visits.append(latest_visit)
            
            # (Optional) Sort visits by date if needed
            visits.sort(key=lambda x: x.visit_date, reverse=True)

        elif 'search_btn' in request.form:
            # Normal Search Filters (Ye waisa hi rahega)
            if search_date:
                query = query.filter_by(next_appt_date=search_date)
            else:
                today = date.today().strftime('%Y-%m-%d')
                query = query.filter_by(next_appt_date=today)
                search_date = today 
            
            if search_treatment:
                query = query.filter(Visit.procedure.contains(search_treatment))
            visits = query.all()
    else:
        # Default View: Today's Appointments
        today = date.today().strftime('%Y-%m-%d')
        visits = query.filter_by(next_appt_date=today).all()
        search_date = today

    return render_template('appointments.html', visits=visits, s_date=search_date, s_treatment=search_treatment, new_patient=new_patient)

# --- WELCOME MESSAGE LOGIC (Sends Once) ---
@app.route('/send_welcome/<int:id>')
def send_welcome(id):
    patient = Patient.query.get_or_404(id)

    if patient.welcome_sent:
        return redirect('/appointments')

    phone = str(patient.phone).strip()
    if len(phone) == 10: phone = "+91" + phone
    elif not phone.startswith('+'): phone = "+" + phone
    
    msg = (f"👋 Welcome to NilkanthSkinCare, {patient.name}! ✨\n\n"
           f"Thank you for registering with us. We are dedicated to your care. 🏥💊\n\n"
           f"📢 For daily skin tips & updates, follow us on Instagram:\n"
           f"👉 https://instagram.com/nilkantha_skin_clinic")
    
    try:
        pywhatkit.sendwhatmsg_instantly(phone, msg, 15, True, 4)
        patient.welcome_sent = True
        db.session.commit()
    except Exception as e:
        print(f"Error: {e}")
        
    return redirect('/appointments')

@app.route('/delete/<int:id>')
def delete_visit(id):
    visit = Visit.query.get_or_404(id)
    db.session.delete(visit)
    db.session.commit()
    return redirect('/appointments')

@app.route('/update_status/<int:id>/<string:new_status>')
def update_status(id, new_status):
    visit = Visit.query.get(id)
    visit.status = new_status
    db.session.commit()
    return redirect('/appointments')

# ==========================================
#  PAGE 3: AUTOMATION
# ==========================================

@app.route('/automation')
def automation_page():
    return render_template('automation.html', logs=[])

@app.route('/send_reminders')
def send_reminders():
    logs = []
    tomorrow = date.today() + timedelta(days=1)
    tomorrow_str = tomorrow.strftime('%Y-%m-%d')
    logs.append(f"Scanning for: {tomorrow_str}...")

    visits = Visit.query.filter_by(next_appt_date=tomorrow_str).all()

    if visits:
        count = 0
        for visit in visits:
            if visit.reminder_sent:
                logs.append(f"⏭️ Skipped {visit.patient.name} (Already Sent).")
                continue 

            patient = visit.patient
            phone = str(patient.phone).strip()
            if len(phone) == 10: phone = "+91" + phone
            elif not phone.startswith('+'): phone = "+" + phone

            # --- REMINDER MESSAGE ---
            msg = (f"Hello {patient.name}, reminder for your {visit.procedure} appointment tomorrow ({tomorrow_str}). 🗓️\n\n"
                   f"How was the result and how was our treatment experience? ✨\n"
                   f"Please give a rating on Google and write your review about our treatment at Nilkanth Skin and Laser Center, Botad. 🏥⭐⭐⭐⭐⭐\n\n"
                   f"👇 Review Link:\n"
                   f"https://g.page/r/PASTE_YOUR_GOOGLE_MAP_LINK_HERE") 
            
            logs.append(f"⏳ Sending to {patient.name}...")
            try:
                pywhatkit.sendwhatmsg_instantly(phone, msg, 20, True, 4)
                
                visit.reminder_sent = True
                db.session.commit()
                
                logs.append("✅ Sent Successfully!")
                count += 1
                time.sleep(5)
            except Exception as e:
                logs.append(f"❌ Failed: {str(e)}")
        
        if count == 0:
            logs.append("✅ No new messages to send.")
        else:
            logs.append(f"✅ Process Completed. Sent {count} new messages.")
    else:
        logs.append("ℹ No appointments found for tomorrow.")

    return render_template('automation.html', logs=logs)

if __name__ == "__main__":
    print("------------------------------------------------")
    print("Server Starting... Go to: http://127.0.0.1:5001")
    print("------------------------------------------------")
    app.run(debug=True, port=5001)