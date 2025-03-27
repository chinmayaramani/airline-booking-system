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
            cur.execute("INSERT INTO Users (Name, Email, Password, is_admin) VALUES (%s, %s, %s, FALSE)",
                        (name, email, hashed_password))
            con.commit()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        except pymysql.MySQLError as e:
            flash("Error: " + str(e), "danger")
        finally:
            con.close()

    return render_template("register.html")

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

# Default seat generation for one flight
def insert_default_seats(flight_number):
    con = get_db_connection()
    cur = con.cursor()

    seat_data = []

    # First Class (Rows 1–2): A, C, D, F
    for row in range(1, 3):
        for seat in ['A', 'C', 'D', 'F']:
            seat_data.append((f"{row}{seat}", 'First Class'))

    # Business Class (Rows 3–7): A, C, D, F
    for row in range(3, 8):
        for seat in ['A', 'C', 'D', 'F']:
            seat_data.append((f"{row}{seat}", 'Business'))

    # Economy Class (Rows 8–35): A, B, C, D, E, F, G
    for row in range(8, 36):
        for seat in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
            seat_data.append((f"{row}{seat}", 'Economy'))

    for seat_number, seat_class in seat_data:
        cur.execute("""
            INSERT INTO Seats (Flight_Number, Seat_Number, Seat_Class, Status)
            VALUES (%s, %s, %s, 'Available')
        """, (flight_number, seat_number, seat_class))

    con.commit()
    con.close()

# 🔥 Function to generate seats for all flights without them
def generate_seats_for_all_flights():
    con = get_db_connection()
    cur = con.cursor()
    cur.execute("SELECT Flight_Number FROM Flights")
    all_flights = [row['Flight_Number'] for row in cur.fetchall()]

    cur.execute("SELECT DISTINCT Flight_Number FROM Seats")
    existing_flights = [row['Flight_Number'] for row in cur.fetchall()]

    flights_missing_seats = [f for f in all_flights if f not in existing_flights]

    for flight in flights_missing_seats:
        print(f"Generating seats for flight: {flight}")
        insert_default_seats(flight)

    con.close()

# Add this route temporarily for development/testing:
@app.route('/generate-seats-for-all')
@login_required
def generate_seats_for_all():
    if not current_user.is_admin:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('home'))

    con = get_db_connection()
    cur = con.cursor()
    cur.execute("SELECT Flight_Number FROM Flights")
    flights = cur.fetchall()
    con.close()

    for flight in flights:
        insert_default_seats(flight["Flight_Number"])

    flash("Seats generated for all flights.", "success")
    return redirect(url_for('flights'))
# ✅ Route to allow admin to generate missing seats
@app.route('/admin/generate-seats')
@login_required
def generate_seats_route():
    if not current_user.is_admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("home"))

    generate_seats_for_all_flights()
    flash("Seats generated for all missing flights!", "success")
    return redirect(url_for("flights"))
@app.route('/admin/all-bookings')
@login_required
def view_all_bookings():
    if not current_user.is_admin:
        flash("Access denied. Admins only.", "danger")
        return redirect(url_for("home"))

    con = get_db_connection()
    cur = con.cursor()
    cur.execute("""
        SELECT b.Booking_ID, b.Seat_Number, b.Total_Price, b.Booking_Date,
               f.Flight_Number, f.Airline, f.Departure, f.Arrival, f.Date, f.Time,
               u.Name AS User_Name, p.Card_Name, p.Card_Number
        FROM Bookings b
        JOIN Flights f ON b.Flight_Number = f.Flight_Number
        JOIN Users u ON b.Passenger_ID = u.User_ID
        LEFT JOIN Payment p ON b.Booking_ID = p.Booking_ID
        ORDER BY b.Booking_Date DESC
    """)
    all_bookings = cur.fetchall()
    con.close()
    return render_template("all_bookings.html", bookings=all_bookings)

@app.route('/admin/clear-booked-seats', methods=['POST'])
@login_required
def clear_booked_seats():
    if not current_user.is_admin:
        flash("Access denied.", "danger")
        return redirect(url_for('home'))

    flight_number = request.form['flight_number']
    con = get_db_connection()
    cur = con.cursor()

    try:
        # Get all booked seats for the selected flight
        cur.execute("SELECT Seat_Number FROM Seats WHERE Flight_Number = %s AND Status = 'Booked'", (flight_number,))
        booked_seats = cur.fetchall()

        for seat in booked_seats:
            seat_number = seat['Seat_Number']

            # Get the associated Booking_ID
            cur.execute("SELECT Booking_ID FROM Bookings WHERE Flight_Number = %s AND Seat_Number = %s",
                        (flight_number, seat_number))
            booking = cur.fetchone()

            if booking:
                booking_id = booking['Booking_ID']

                # Delete from Payment and Bookings tables
                cur.execute("DELETE FROM Payment WHERE Booking_ID = %s", (booking_id,))
                cur.execute("DELETE FROM Bookings WHERE Booking_ID = %s", (booking_id,))

            # Mark the seat as available again
            cur.execute("UPDATE Seats SET Status = 'Available' WHERE Flight_Number = %s AND Seat_Number = %s",
                        (flight_number, seat_number))

        con.commit()
        flash(f"Cleared booked seats and related bookings for flight {flight_number}.", "success")

    except Exception as e:
        con.rollback()
        flash(f"Error clearing booked seats: {e}", "danger")
    finally:
        con.close()

    return redirect(url_for('flights'))


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

    # Get dropdown values
    cur.execute("SELECT DISTINCT Departure FROM Flights")
    departures = [row['Departure'] for row in cur.fetchall()]

    cur.execute("SELECT DISTINCT Arrival FROM Flights")
    arrivals = [row['Arrival'] for row in cur.fetchall()]

    # Filters
    departure = request.args.get('departure')
    arrival = request.args.get('arrival')
    date = request.args.get('date')
    min_price = request.args.get('min_price')
    max_price = request.args.get('max_price')
    page = request.args.get('page', 1, type=int)
    flights_per_page = 10

    base_query = "SELECT * FROM Flights WHERE 1=1"
    count_query = "SELECT COUNT(*) as total FROM Flights WHERE 1=1"
    values = []

    # Apply filters
    if departure:
        base_query += " AND Departure = %s"
        count_query += " AND Departure = %s"
        values.append(departure)
    if arrival:
        base_query += " AND Arrival = %s"
        count_query += " AND Arrival = %s"
        values.append(arrival)
    if date:
        base_query += " AND Date = %s"
        count_query += " AND Date = %s"
        values.append(date)
    if min_price:
        base_query += " AND Price >= %s"
        count_query += " AND Price >= %s"
        values.append(min_price)
    if max_price:
        base_query += " AND Price <= %s"
        count_query += " AND Price <= %s"
        values.append(max_price)

    # Total count
    cur.execute(count_query, values)
    total_flights = cur.fetchone()['total']
    total_pages = (total_flights + flights_per_page - 1) // flights_per_page

    # Add LIMIT + OFFSET to base query
    base_query += " LIMIT %s OFFSET %s"
    values += [flights_per_page, (page - 1) * flights_per_page]

    cur.execute(base_query, values)
    flights = cur.fetchall()
    con.close()

    return render_template(
        "flights.html",
        flights=flights,
        departures=departures,
        arrivals=arrivals,
        page=page,
        total_pages=total_pages
    )


@app.route('/my-bookings')
@login_required
def my_bookings():
    con = get_db_connection()
    cur = con.cursor()
    cur.execute("""
        SELECT b.Booking_ID, b.Seat_Number, b.Total_Price, b.Booking_Date,
               f.Flight_Number, f.Airline, f.Departure, f.Arrival, f.Date, f.Time,
               p.Card_Name, p.Card_Number
        FROM Bookings b
        JOIN Flights f ON b.Flight_Number = f.Flight_Number
        LEFT JOIN Payment p ON b.Booking_ID = p.Booking_ID
        WHERE b.Passenger_ID = %s
        ORDER BY b.Booking_Date DESC
    """, (current_user.id,))
    bookings = cur.fetchall()
    con.close()
    return render_template('my_bookings.html', bookings=bookings)

@app.route('/cancel-booking/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    con = get_db_connection()
    cur = con.cursor()
    try:
        cur.execute("SELECT Flight_Number, Seat_Number FROM Bookings WHERE Booking_ID = %s AND Passenger_ID = %s",
                    (booking_id, current_user.id))
        booking = cur.fetchone()

        if not booking:
            flash("Booking not found or unauthorized.", "danger")
            return redirect(url_for('my_bookings'))

        # Delete from Payment and Bookings
        cur.execute("DELETE FROM Payment WHERE Booking_ID = %s", (booking_id,))
        cur.execute("DELETE FROM Bookings WHERE Booking_ID = %s", (booking_id,))

        # Make seat available again
        cur.execute("""
            UPDATE Seats SET Status = 'Available'
            WHERE Flight_Number = %s AND Seat_Number = %s
        """, (booking['Flight_Number'], booking['Seat_Number']))

        con.commit()
        flash("Booking cancelled successfully!", "success")
    except Exception as e:
        flash(f"Error cancelling booking: {e}", "danger")
    finally:
        con.close()

    return redirect(url_for('my_bookings'))

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
    from collections import defaultdict

    def generate_seat_rows(seats):
        seat_rows = defaultdict(lambda: [None] * 7)
        column_mapping = {'A': 0, 'B': 1, 'C': 2, 'D': 3, 'E': 4, 'F': 5, 'G': 6}
        for seat in seats:
            seat_number = seat["Seat_Number"]
            row_part = ''.join(filter(str.isdigit, seat_number))
            col_part = ''.join(filter(str.isalpha, seat_number)).upper()
            if not row_part or col_part not in column_mapping:
                continue
            row = int(row_part)
            col_index = column_mapping[col_part]
            seat_rows[row][col_index] = seat
        return dict(sorted(seat_rows.items()))

    try:
        flight_number = request.form['flight_number']
        con = get_db_connection()
        cur = con.cursor()

        cur.execute("SELECT Price FROM Flights WHERE Flight_Number = %s", (flight_number,))
        flight = cur.fetchone()
        if not flight:
            flash("Flight not found.", "danger")
            return redirect(url_for('flights'))

        base_price = float(flight['Price'])

        cur.execute("""
            SELECT Seat_Number, Seat_Class, Status
            FROM Seats
            WHERE Flight_Number = %s
            ORDER BY Seat_Number
        """, (flight_number,))
        seats = cur.fetchall()

        for seat in seats:
            seat["Booked"] = seat["Status"] == "Booked"
            seat["Price"] = round(base_price * 1.5 if seat["Seat_Class"] == "First Class"
                                  else base_price * 1.25 if seat["Seat_Class"] == "Business"
                                  else base_price, 2)

        seat_rows = generate_seat_rows(seats)
        con.close()

        return render_template(
            "select_seat.html",
            flight_number=flight_number,
            seat_rows=seat_rows,
            is_admin=current_user.is_authenticated and current_user.is_admin
        )

    except Exception as e:
        return f"Error loading seat selection: {e}"
@app.route('/admin/reset-seats/<flight_number>', methods=['POST'])
@login_required
def reset_seats(flight_number):
    if not current_user.is_admin:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("home"))

    try:
        con = get_db_connection()
        cur = con.cursor()

        # Reset all booked seats to Available
        cur.execute("""
            UPDATE Seats
            SET Status = 'Available'
            WHERE Flight_Number = %s AND Status = 'Booked'
        """, (flight_number,))
        con.commit()
        flash(f"All booked seats for flight {flight_number} have been reset to available.", "success")

    except Exception as e:
        flash(f"Error resetting seats: {e}", "danger")
    finally:
        con.close()

    return redirect(url_for('flights'))

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
    card_number = request.form['card_number']
    card_name = request.form['name']

    con = get_db_connection()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO Bookings (Passenger_ID, Flight_Number, Booking_Date, Seat_Number, Total_Price)
        VALUES (%s, %s, NOW(), %s, %s)
    """, (current_user.id, flight_number, seat_number, price))

    cur.execute("""
        INSERT INTO Payment (Booking_ID, Payment_Date, Amount, Payment_Status, Card_Name, Card_Number)
        VALUES (LAST_INSERT_ID(), NOW(), %s, 'Completed', %s, %s)
    """, (price, card_name, card_number))

    cur.execute("""
        UPDATE Seats SET Status = 'Booked' WHERE Flight_Number = %s AND Seat_Number = %s
    """, (flight_number, seat_number))

    con.commit()
    con.close()
    flash("Booking confirmed successfully!", "success")
    return redirect(url_for("home"))


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
        except Exception as e:
            flash(f"Error: {e}", "danger")
        finally:
            con.close()
            return redirect(url_for('flights'))

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
