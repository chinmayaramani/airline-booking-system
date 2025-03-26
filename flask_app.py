from flask import Flask, render_template, request, redirect, url_for, flash
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import pymysql
import credentials

# Initialize Flask app
app = Flask(__name__, template_folder="templates")
app.secret_key = "your_secret_key"

# Initialize bcrypt for password hashing
bcrypt = Bcrypt(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Function to connect to MySQL database
def get_db_connection():
    return pymysql.connect(
        host=credentials.DB_HOST,
        user=credentials.DB_USER,
        password=credentials.DB_PWD,
        database=credentials.DB_NAME,
        cursorclass=pymysql.cursors.DictCursor
    )

# User class for authentication
class User(UserMixin):
    def __init__(self, id, name, email):
        self.id = id
        self.name = name
        self.email = email

# Load user function for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    con = get_db_connection()
    cur = con.cursor()
    cur.execute("SELECT * FROM Users WHERE User_ID = %s", (user_id,))
    user = cur.fetchone()
    con.close()
    if user:
        return User(user["User_ID"], user["Name"], user["Email"])
    return None

# Home page
@app.route('/')
def home():
    booking = None
    if current_user.is_authenticated:
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("""
            SELECT * FROM Bookings WHERE Passenger_ID = %s ORDER BY Booking_Date DESC LIMIT 1
        """, (current_user.id,))
        booking = cur.fetchone()
        con.close()
    return render_template("index.html", booking=booking)

# View Flights
@app.route('/flights')
def flights():
    con = get_db_connection()
    cur = con.cursor()
    cur.execute("SELECT * FROM Flights")
    flights = cur.fetchall()
    con.close()
    return render_template("flights.html", flights=flights)

# Select Seat
@app.route('/select-seat', methods=['POST'])
@login_required
def select_seat():
    try:
        flight_number = request.form['flight_number']
        con = get_db_connection()
        cur = con.cursor()

        # Pull seats
        cur.execute("""
            SELECT s.Seat_Number, s.Flight_Number, s.Seat_Class,
                CASE 
                    WHEN s.Seat_Class = 'Business' THEN 1000
                    WHEN s.Seat_Class = 'First Class' THEN 1500
                    ELSE 500
                END AS Price,
                s.Status
            FROM Seats s
            WHERE s.Flight_Number = %s
            ORDER BY s.Seat_Number
        """, (flight_number,))
        seats = cur.fetchall()

        print("DEBUG: Retrieved seats →", seats)  # ✅ ADDED

        for seat in seats:
            seat["Booked"] = seat["Status"] == "Booked"

        con.close()
        return render_template("select_seat.html", seats=seats, flight_number=flight_number)
    
    except Exception as e:
        return f"An error occurred: {e}"


# Payment Page
@app.route('/payment', methods=['POST'])
@login_required
def payment():
    flight_number = request.form['flight_number']
    seat_number = request.form['seat_number']
    return render_template("payment.html", flight_number=flight_number, seat_number=seat_number)

# Confirm Booking
@app.route('/confirm-booking', methods=['POST'])
@login_required
def confirm_booking():
    flight_number = request.form['flight_number']
    seat_number = request.form['seat_number']

    con = get_db_connection()
    cur = con.cursor()

    # Insert into Bookings
    cur.execute("""
        INSERT INTO Bookings (Passenger_ID, Flight_Number, Booking_Date, Seat_Number, Total_Price)
        VALUES (%s, %s, NOW(), %s, 500)
    """, (current_user.id, flight_number, seat_number))

    # Insert into Payment
    cur.execute("""
        INSERT INTO Payment (Booking_ID, Date, Amount, Transaction)
        VALUES (LAST_INSERT_ID(), NOW(), 500, 'Completed')
    """)

    con.commit()
    con.close()

    flash("Booking confirmed successfully!", "success")
    return redirect(url_for("home"))

# Book via direct POST (legacy, optional)
@app.route('/book', methods=['POST'])
@login_required
def book():
    flight_number = request.form['flight_number']
    con = get_db_connection()
    cur = con.cursor()
    cur.execute("INSERT INTO Bookings (Passenger_ID, Flight_Number, Booking_Date, Total_Price) VALUES (%s, %s, NOW(), 500)", (current_user.id, flight_number))
    con.commit()
    con.close()
    flash("Booking successful!", "success")
    return redirect(url_for("flights"))

# User Registration
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")

        con = get_db_connection()
        cur = con.cursor()
        try:
            cur.execute("INSERT INTO Users (Name, Email, Password) VALUES (%s, %s, %s)", (name, email, hashed_password))
            con.commit()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        except pymysql.MySQLError as e:
            flash("Error: " + str(e), "danger")
        finally:
            con.close()

    return render_template("register.html")

# User Login
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        con = get_db_connection()
        cur = con.cursor()
        cur.execute("SELECT * FROM Users WHERE Email = %s", (email,))
        user = cur.fetchone()
        con.close()

        if user and bcrypt.check_password_hash(user["Password"], password):
            login_user(User(user["User_ID"], user["Name"], user["Email"]))
            flash("Login successful!", "success")
            return redirect(url_for("home"))

        flash("Invalid credentials. Please try again.", "danger")

    return render_template("login.html")

# User Logout
@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))

# Run the Flask app
if __name__ == '__main__':
    app.run(debug=True)
