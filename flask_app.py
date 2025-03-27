from flask import Flask, render_template, request, redirect, url_for, flash
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import pymysql
import credentials

app = Flask(__name__, template_folder="templates")
app.secret_key = "your_secret_key"

bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

def get_db_connection():
    return pymysql.connect(
        host=credentials.DB_HOST,
        user=credentials.DB_USER,
        password=credentials.DB_PWD,
        database=credentials.DB_NAME,
        cursorclass=pymysql.cursors.DictCursor
    )

class User(UserMixin):
    def __init__(self, id, name, email, is_admin=False):
        self.id = id
        self.name = name
        self.email = email
        self.is_admin = is_admin

@login_manager.user_loader
def load_user(user_id):
    con = get_db_connection()
    cur = con.cursor()
    cur.execute("SELECT * FROM Users WHERE User_ID = %s", (user_id,))
    user = cur.fetchone()
    con.close()
    if user:
        return User(user["User_ID"], user["Name"], user["Email"], user["is_admin"])
    return None

def insert_default_seats(flight_number):
    con = get_db_connection()
    cur = con.cursor()
    seats = [
        ('A1', 'Economy'), ('A2', 'Economy'), ('A3', 'Economy'), ('A4', 'Economy'),
        ('B1', 'Business'), ('B2', 'Business'),
        ('C1', 'First Class'), ('C2', 'First Class')
    ]
    for seat_number, seat_class in seats:
        cur.execute("""
            INSERT INTO Seats (Flight_Number, Seat_Number, Seat_Class, Status)
            VALUES (%s, %s, %s, 'Available')
        """, (flight_number, seat_number, seat_class))
    con.commit()
    con.close()

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

@app.route('/flights')
def flights():
    con = get_db_connection()
    cur = con.cursor()
    cur.execute("SELECT * FROM Flights")
    flights = cur.fetchall()
    con.close()
    return render_template("flights.html", flights=flights)

@app.route('/add-flight', methods=['GET', 'POST'])
@login_required
def add_flight():
    if not current_user.is_admin:
        flash("Unauthorized access. Admins only.", "danger")
        return redirect(url_for('home'))

    if request.method == 'POST':
        flight_number = request.form['flight_number']
        airline = request.form['airline']
        departure = request.form['departure']
        arrival = request.form['arrival']
        date = request.form['date']
        time = request.form['time']
        duration = request.form['duration']
        price = request.form['price']

        con = get_db_connection()
        cur = con.cursor()

        try:
            cur.execute("""
                INSERT INTO Flights (Flight_Number, Airline, Departure, Arrival, Date, Time, Duration, Price)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (flight_number, airline, departure, arrival, date, time, duration, price))
            con.commit()
            insert_default_seats(flight_number)
            flash(f"Flight {flight_number} added with default seats!", "success")
            return redirect(url_for('flights'))
        except Exception as e:
            flash(f"Error: {e}", "danger")
        finally:
            con.close()

    return render_template('add_flight.html')

@app.route('/select-seat', methods=['POST'])
@login_required
def select_seat():
    try:
        flight_number = request.form['flight_number']
        con = get_db_connection()
        cur = con.cursor()
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
        for seat in seats:
            seat["Booked"] = seat["Status"] == "Booked"
        con.close()
        return render_template("select_seat.html", seats=seats, flight_number=flight_number)
    except Exception as e:
        return f"An error occurred: {e}"

@app.route('/payment', methods=['POST'])
@login_required
def payment():
    flight_number = request.form['flight_number']
    seat_number = request.form['seat_number']
    seat_class = request.form.get('seat_class', 'Economy')
    price = request.form.get('price', 500)
    return render_template("payment.html", flight_number=flight_number, seat_number=seat_number, seat_class=seat_class, price=price)

@app.route('/confirm-booking', methods=['POST'])
@login_required
def confirm_booking():
    flight_number = request.form['flight_number']
    seat_number = request.form['seat_number']
    price = request.form['price']
    con = get_db_connection()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO Bookings (Passenger_ID, Flight_Number, Booking_Date, Seat_Number, Total_Price)
        VALUES (%s, %s, NOW(), %s, %s)
    """, (current_user.id, flight_number, seat_number, price))
    cur.execute("""
        INSERT INTO Payment (Booking_ID, Date, Amount, Transaction)
        VALUES (LAST_INSERT_ID(), NOW(), %s, 'Completed')
    """, (price,))
    cur.execute("""
        UPDATE Seats SET Status = 'Booked' WHERE Flight_Number = %s AND Seat_Number = %s
    """, (flight_number, seat_number))
    con.commit()
    con.close()
    flash("Booking confirmed successfully!", "success")
    return redirect(url_for("home"))

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
            cur.execute("INSERT INTO Users (Name, Email, Password, is_admin) VALUES (%s, %s, %s, FALSE)", (name, email, hashed_password))
            con.commit()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        except pymysql.MySQLError as e:
            flash("Error: " + str(e), "danger")
        finally:
            con.close()

    return render_template("register.html")

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
            login_user(User(user["User_ID"], user["Name"], user["Email"], user["is_admin"]))
            flash("Login successful!", "success")
            return redirect(url_for("home"))

        flash("Invalid credentials. Please try again.", "danger")

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))

@app.route('/edit-flight/<flight_number>', methods=['GET', 'POST'])
@login_required
def edit_flight(flight_number):
    if not current_user.is_admin:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('flights'))

    con = get_db_connection()
    cur = con.cursor()

    if request.method == 'POST':
        new_flight_number = request.form['new_flight_number']
        airline = request.form['airline']
        departure = request.form['departure']
        arrival = request.form['arrival']
        date = request.form['date']
        time = request.form['time']
        duration = request.form['duration']
        price = request.form['price']

        try:
            cur.execute("""
                UPDATE Flights
                SET Flight_Number=%s, Airline=%s, Departure=%s, Arrival=%s,
                    Date=%s, Time=%s, Duration=%s, Price=%s
                WHERE Flight_Number=%s
            """, (new_flight_number, airline, departure, arrival, date, time, duration, price, flight_number))

            cur.execute("""
                UPDATE Seats SET Flight_Number=%s WHERE Flight_Number=%s
            """, (new_flight_number, flight_number))

            con.commit()
            flash("Flight updated successfully!", "success")
            return redirect(url_for('flights'))

        except Exception as e:
            flash(f"Error: {e}", "danger")

        finally:
            con.close()
            return redirect(url_for('flights'))

    else:
        # Only fetch and render on GET request
        cur.execute("SELECT * FROM Flights WHERE Flight_Number = %s", (flight_number,))
        flight = cur.fetchone()
        con.close()
        return render_template('edit_flight.html', flight=flight)


@app.route('/delete-flight/<flight_number>', methods=['POST'])
@login_required
def delete_flight(flight_number):
    if not current_user.is_admin:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('flights'))

    con = get_db_connection()
    cur = con.cursor()
    try:
        cur.execute("DELETE FROM Flights WHERE Flight_Number = %s", (flight_number,))
        cur.execute("DELETE FROM Seats WHERE Flight_Number = %s", (flight_number,))
        con.commit()
        flash("Flight and related seats deleted successfully.", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        con.close()

    return redirect(url_for('flights'))

if __name__ == '__main__':
    app.run(debug=True)
