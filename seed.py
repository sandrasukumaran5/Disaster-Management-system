import sqlite3
import hashlib

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def seed():
    conn = sqlite3.connect('reliefops.db')
    c = conn.cursor()

    # Clear existing data
    c.execute("DELETE FROM users")
    c.execute("DELETE FROM disaster")
    c.execute("DELETE FROM relief_camp")
    c.execute("DELETE FROM resource")
    c.execute("DELETE FROM resource_shortage")
    c.execute("DELETE FROM resource_allocation")
    c.execute("DELETE FROM donation")
    c.execute("DELETE FROM volunteer_camp")

    # Add Admin
    c.execute("INSERT INTO users (full_name, email, password_hash, role, joined_date) VALUES (?,?,?,?,?)",
              ('System Admin', 'admin@reliefops.com', hash_pw('admin123'), 'admin', '2026-01-01'))
    admin_id = c.lastrowid

    # Add Donors
    c.execute("INSERT INTO users (full_name, email, password_hash, role, organization, joined_date) VALUES (?,?,?,?,?,?)",
              ('John Doe', 'john@example.com', hash_pw('password'), 'donor', 'Red Cross', '2026-02-15'))
    c.execute("INSERT INTO users (full_name, email, password_hash, role, organization, joined_date) VALUES (?,?,?,?,?,?)",
              ('Jane Smith', 'jane@example.com', hash_pw('password'), 'donor', 'UNICEF', '2026-03-01'))

    # Add Volunteers
    c.execute("INSERT INTO users (full_name, email, password_hash, role, joined_date) VALUES (?,?,?,?,?)",
              ('Mike Vol', 'mike@test.com', hash_pw('password'), 'volunteer', '2026-03-10'))
    c.execute("INSERT INTO users (full_name, email, password_hash, role, joined_date) VALUES (?,?,?,?,?)",
              ('Sarah Vol', 'sarah@test.com', hash_pw('password'), 'volunteer', '2026-03-12'))

    # Add Disasters
    c.execute("INSERT INTO disaster (disaster_name, disaster_type, location, severity_level, status, start_date, lat, lng) VALUES (?,?,?,?,?,?,?,?)",
              ('Kerala Floods', 'Flood', 'Wayand, Kerala', 'Severe', 'Active', '2026-03-15', 11.6854, 76.1320))
    flood_id = c.lastrowid
    
    c.execute("INSERT INTO disaster (disaster_name, disaster_type, location, severity_level, status, start_date, lat, lng) VALUES (?,?,?,?,?,?,?,?)",
              ('Cyclone Amphan', 'Cyclone', 'Odisha Coast', 'High', 'Monitoring', '2026-03-20', 20.2725, 85.8338))

    # Add Camps
    c.execute("INSERT INTO relief_camp (camp_name, location, total_capacity, current_occupancy, status, opened_date, disaster_id) VALUES (?,?,?,?,?,?,?)",
              ('Wayand Central School', 'Kalpetta', 500, 320, 'Active', '2026-03-16', flood_id))
    c.execute("INSERT INTO relief_camp (camp_name, location, total_capacity, current_occupancy, status, opened_date, disaster_id) VALUES (?,?,?,?,?,?,?)",
              ('St. Marys Hall', 'Meppadi', 200, 195, 'Full', '2026-03-17', flood_id))

    # Add Resources
    c.execute("INSERT INTO resource (resource_name, category, unit, quantity_available, min_threshold) VALUES (?,?,?,?,?)",
              ('Drinking Water', 'Water', 'Litres', 1200, 500))
    c.execute("INSERT INTO resource (resource_name, category, unit, quantity_available, min_threshold) VALUES (?,?,?,?,?)",
              ('Paracetamol', 'Medical', 'Packets', 45, 100))
    c.execute("INSERT INTO resource (resource_name, category, unit, quantity_available, min_threshold) VALUES (?,?,?,?,?)",
              ('Rice', 'Food', 'KG', 800, 200))
    c.execute("INSERT INTO resource (resource_name, category, unit, quantity_available, min_threshold) VALUES (?,?,?,?,?)",
              ('Blankets', 'Shelter', 'Units', 12, 50))

    conn.commit()
    conn.close()
    print("✅ Database seeded successfully!")

if __name__ == "__main__":
    seed()
