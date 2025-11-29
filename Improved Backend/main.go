package main

import (
	"database/sql"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

// SensorData represents the data structure from BME680 sensor
type SensorData struct {
	Temperature   float64 `json:"temperature"`
	Humidity      float64 `json:"humidity"`
	Pressure      float64 `json:"pressure"`
	GasResistance *int    `json:"gas_resistance,omitempty"` // BME680 specific
	AQI           *int    `json:"aqi,omitempty"`            // Air Quality Index
}

// DateQuery represents a date query for IST timezone
type DateQuery struct {
	Day   int `json:"day"`
	Month int `json:"month"`
	Year  int `json:"year"`
}

// DateRangeQuery represents a date range query
type DateRangeQuery struct {
	StartDate string `json:"startDate"`
	EndDate   string `json:"endDate"`
}

// DatabaseRecord represents a record from the database
type DatabaseRecord struct {
	ID            int       `json:"id"`
	Temperature   float64   `json:"temperature"`
	Humidity      float64   `json:"humidity"`
	Pressure      float64   `json:"pressure"`
	GasResistance *int      `json:"gas_resistance,omitempty"` // Nullable
	Timestamp     time.Time `json:"timestamp"`
}

func main() {
	// Open database connection
	db, err := sql.Open("sqlite3", "./data.db")
	if err != nil {
		log.Fatal("Failed to open database:", err)
	}
	defer db.Close()

	// Test database connection
	if err := db.Ping(); err != nil {
		log.Fatal("Failed to ping database:", err)
	}

	// Create table if not exists (with gas_resistance and aqi columns for BME680)
	createTableSQL := `CREATE TABLE IF NOT EXISTS temp (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		temperature REAL NOT NULL,
		humidity REAL NOT NULL,
		pressure REAL NOT NULL,
		gas_resistance INTEGER,
		aqi INTEGER,
		timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
	);`

	_, err = db.Exec(createTableSQL)
	if err != nil {
		log.Fatal("Failed to create table:", err)
	}

	// Check and add gas_resistance column if it doesn't exist (for migration from old schema)
	// SQLite doesn't support IF NOT EXISTS for ALTER TABLE, so we check first
	var gasResistanceExists bool
	err = db.QueryRow(`SELECT COUNT(*) FROM pragma_table_info('temp') WHERE name='gas_resistance'`).Scan(&gasResistanceExists)
	if err == nil && !gasResistanceExists {
		_, err = db.Exec(`ALTER TABLE temp ADD COLUMN gas_resistance INTEGER;`)
		if err != nil {
			log.Printf("Warning: Failed to add gas_resistance column: %v", err)
		} else {
			log.Println("Added gas_resistance column to existing table")
		}
	}

	// Check and add aqi column if it doesn't exist
	var aqiExists bool
	err = db.QueryRow(`SELECT COUNT(*) FROM pragma_table_info('temp') WHERE name='aqi'`).Scan(&aqiExists)
	if err == nil && !aqiExists {
		_, err = db.Exec(`ALTER TABLE temp ADD COLUMN aqi INTEGER;`)
		if err != nil {
			log.Printf("Warning: Failed to add aqi column: %v", err)
		} else {
			log.Println("Added aqi column to existing table")
		}
	}

	log.Println("Database schema verified and ready")

	// Create index on timestamp for better query performance
	_, err = db.Exec(`CREATE INDEX IF NOT EXISTS idx_timestamp ON temp(timestamp);`)
	if err != nil {
		log.Println("Warning: Failed to create index:", err)
	}

	// Serve static files
	fs := http.FileServer(http.Dir("."))
	http.Handle("/", fs)

	// API: Record sensor data
	http.HandleFunc("/temprec", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Only POST method is allowed", http.StatusMethodNotAllowed)
			return
		}

		var data SensorData
		if err := json.NewDecoder(r.Body).Decode(&data); err != nil {
			http.Error(w, fmt.Sprintf("Invalid JSON: %v", err), http.StatusBadRequest)
			return
		}

		// Validate data ranges
		if data.Temperature < -50 || data.Temperature > 100 {
			http.Error(w, "Temperature out of valid range (-50 to 100°C)", http.StatusBadRequest)
			return
		}
		if data.Humidity < 0 || data.Humidity > 100 {
			http.Error(w, "Humidity out of valid range (0 to 100%)", http.StatusBadRequest)
			return
		}
		if data.Pressure < 300 || data.Pressure > 1100 {
			http.Error(w, "Pressure out of valid range (300 to 1100 hPa)", http.StatusBadRequest)
			return
		}

		// Store current time in UTC
		utc := time.Now().UTC()

		// Insert data into database
		var gasResistance *int
		if data.GasResistance != nil && *data.GasResistance > 0 {
			gasResistance = data.GasResistance
		}

		sqlStmt := `INSERT INTO temp (temperature, humidity, pressure, gas_resistance, aqi, timestamp) VALUES (?, ?, ?, ?, ?, ?)`
		_, err := db.Exec(sqlStmt, data.Temperature, data.Humidity, data.Pressure, gasResistance, data.AQI, utc.Format(time.RFC3339))
		if err != nil {
			log.Printf("Database error: %v", err)
			http.Error(w, fmt.Sprintf("Database error: %v", err), http.StatusInternalServerError)
			return
		}

		aqiStr := "N/A"
		if data.AQI != nil {
			aqiStr = fmt.Sprintf("%d", *data.AQI)
		}
		log.Printf("Data recorded: Temp=%.2f°C, Hum=%.2f%%, Pres=%.2fhPa, Gas=%v, AQI=%s",
			data.Temperature, data.Humidity, data.Pressure, gasResistance, aqiStr)

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "success", "message": "Data recorded successfully"})
	})

	// API: Get latest reading
	http.HandleFunc("/temp", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "Only GET method is allowed", http.StatusMethodNotAllowed)
			return
		}

		sqlStmt := `SELECT id, temperature, humidity, pressure, gas_resistance, aqi, timestamp FROM temp ORDER BY id DESC LIMIT 1`
		row := db.QueryRow(sqlStmt)

		var id int
		var temperature, humidity, pressure float64
		var gasResistance, aqi sql.NullInt64
		var timestampStr string

		err := row.Scan(&id, &temperature, &humidity, &pressure, &gasResistance, &aqi, &timestampStr)
		if err != nil {
			if err == sql.ErrNoRows {
				http.Error(w, "No data available", http.StatusNotFound)
				return
			}
			log.Printf("Database error: %v", err)
			http.Error(w, fmt.Sprintf("Database error: %v", err), http.StatusInternalServerError)
			return
		}

		// Parse timestamp
		timestamp, err := time.Parse(time.RFC3339, timestampStr)
		if err != nil {
			log.Printf("Timestamp parse error: %v", err)
			http.Error(w, "Invalid timestamp format", http.StatusInternalServerError)
			return
		}

		results := map[string]interface{}{
			"temperature": temperature,
			"humidity":    humidity,
			"pressure":    pressure,
			"timestamp":   timestamp.Format(time.RFC3339),
		}

		if gasResistance.Valid {
			results["gas_resistance"] = gasResistance.Int64
		}

		if aqi.Valid {
			results["aqi"] = aqi.Int64
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(results)
	})

	// API: Get daily statistics (IST timezone)
	http.HandleFunc("/tempstat", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Only POST method is allowed", http.StatusMethodNotAllowed)
			return
		}

		var dateQuery DateQuery
		if err := json.NewDecoder(r.Body).Decode(&dateQuery); err != nil {
			http.Error(w, fmt.Sprintf("Invalid JSON: %v", err), http.StatusBadRequest)
			return
		}

		// Validate date
		if dateQuery.Day < 1 || dateQuery.Day > 31 || dateQuery.Month < 1 || dateQuery.Month > 12 || dateQuery.Year < 2000 {
			http.Error(w, "Invalid date", http.StatusBadRequest)
			return
		}

		// Create IST location (UTC+5:30)
		istLocation := time.FixedZone("IST", 5*60*60+30*60)

		// Create start and end of day in IST
		istStart := time.Date(dateQuery.Year, time.Month(dateQuery.Month), dateQuery.Day, 0, 0, 0, 0, istLocation)
		istEnd := istStart.Add(24 * time.Hour)

		// Convert to UTC for database query
		utcStart := istStart.UTC()
		utcEnd := istEnd.UTC()

		sqlStmt := `
			SELECT 
				MAX(temperature), MIN(temperature), AVG(temperature),
				MAX(humidity), MIN(humidity), AVG(humidity),
				MAX(pressure), MIN(pressure), AVG(pressure),
				MAX(gas_resistance), MIN(gas_resistance), AVG(gas_resistance),
				MAX(aqi), MIN(aqi), AVG(aqi)
			FROM temp 
			WHERE timestamp >= ? AND timestamp < ?`

		row := db.QueryRow(sqlStmt, utcStart.Format(time.RFC3339), utcEnd.Format(time.RFC3339))

		var maxTemp, minTemp, avgTemp sql.NullFloat64
		var maxHum, minHum, avgHum sql.NullFloat64
		var maxPres, minPres, avgPres sql.NullFloat64
		var maxGas, minGas sql.NullInt64
		var avgGas sql.NullFloat64
		var maxAQI, minAQI sql.NullInt64
		var avgAQI sql.NullFloat64

		err := row.Scan(&maxTemp, &minTemp, &avgTemp, &maxHum, &minHum, &avgHum,
			&maxPres, &minPres, &avgPres, &maxGas, &minGas, &avgGas,
			&maxAQI, &minAQI, &avgAQI)

		if err != nil {
			if err == sql.ErrNoRows {
				http.Error(w, "No data available for the specified date", http.StatusNotFound)
				return
			}
			log.Printf("Database error: %v", err)
			http.Error(w, fmt.Sprintf("Database error: %v", err), http.StatusInternalServerError)
			return
		}

		results := make(map[string]interface{})

		if maxTemp.Valid {
			results["max_temperature"] = maxTemp.Float64
			results["min_temperature"] = minTemp.Float64
			results["avg_temperature"] = avgTemp.Float64
		}
		if maxHum.Valid {
			results["max_humidity"] = maxHum.Float64
			results["min_humidity"] = minHum.Float64
			results["avg_humidity"] = avgHum.Float64
		}
		if maxPres.Valid {
			results["max_pressure"] = maxPres.Float64
			results["min_pressure"] = minPres.Float64
			results["avg_pressure"] = avgPres.Float64
		}
		if maxGas.Valid {
			results["max_gas_resistance"] = maxGas.Int64
			results["min_gas_resistance"] = minGas.Int64
			if avgGas.Valid {
				results["avg_gas_resistance"] = avgGas.Float64
			}
		}
		if maxAQI.Valid {
			results["max_aqi"] = maxAQI.Int64
			results["min_aqi"] = minAQI.Int64
			if avgAQI.Valid {
				results["avg_aqi"] = avgAQI.Float64
			}
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(results)
	})

	// API: Get daily data as CSV
	http.HandleFunc("/tempget", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Only POST method is allowed", http.StatusMethodNotAllowed)
			return
		}

		var dateQuery DateQuery
		if err := json.NewDecoder(r.Body).Decode(&dateQuery); err != nil {
			http.Error(w, fmt.Sprintf("Invalid JSON: %v", err), http.StatusBadRequest)
			return
		}

		// Create IST location
		istLocation := time.FixedZone("IST", 5*60*60+30*60)
		istStart := time.Date(dateQuery.Year, time.Month(dateQuery.Month), dateQuery.Day, 0, 0, 0, 0, istLocation)
		istEnd := istStart.Add(24 * time.Hour)
		utcStart := istStart.UTC()
		utcEnd := istEnd.UTC()

		sqlStmt := `
			SELECT temperature, humidity, pressure, gas_resistance, aqi, timestamp 
			FROM temp 
			WHERE timestamp >= ? AND timestamp < ?
			ORDER BY timestamp ASC`

		rows, err := db.Query(sqlStmt, utcStart.Format(time.RFC3339), utcEnd.Format(time.RFC3339))
		if err != nil {
			log.Printf("Database error: %v", err)
			http.Error(w, fmt.Sprintf("Database error: %v", err), http.StatusInternalServerError)
			return
		}
		defer rows.Close()

		w.Header().Set("Content-Type", "text/csv")
		w.Header().Set("Content-Disposition", "attachment; filename=weather_data.csv")

		writer := csv.NewWriter(w)
		defer writer.Flush()

		// Write CSV header
		header := []string{"Temperature", "Humidity", "Pressure", "Gas_Resistance", "AQI", "Timestamp"}
		if err := writer.Write(header); err != nil {
			return
		}

		// Write data rows
		for rows.Next() {
			var temperature, humidity, pressure float64
			var gasResistance, aqi sql.NullInt64
			var timestampStr string

			if err := rows.Scan(&temperature, &humidity, &pressure, &gasResistance, &aqi, &timestampStr); err != nil {
				log.Printf("Row scan error: %v", err)
				continue
			}

			// Parse and convert timestamp to IST for display
			timestamp, err := time.Parse(time.RFC3339, timestampStr)
			if err != nil {
				log.Printf("Timestamp parse error: %v", err)
				continue
			}

			istLocation := time.FixedZone("IST", 5*60*60+30*60)
			istTime := timestamp.In(istLocation)

			gasStr := ""
			if gasResistance.Valid {
				gasStr = fmt.Sprintf("%d", gasResistance.Int64)
			}

			aqiStr := ""
			if aqi.Valid {
				aqiStr = fmt.Sprintf("%d", aqi.Int64)
			}

			record := []string{
				fmt.Sprintf("%.2f", temperature),
				fmt.Sprintf("%.2f", humidity),
				fmt.Sprintf("%.2f", pressure),
				gasStr,
				aqiStr,
				istTime.Format("2006-01-02 15:04:05 IST"),
			}
			if err := writer.Write(record); err != nil {
				log.Printf("CSV write error: %v", err)
			}
		}
	})

	// API: Get date range data
	http.HandleFunc("/tempdaterange", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Only POST method is allowed", http.StatusMethodNotAllowed)
			return
		}

		var dateRange DateRangeQuery
		if err := json.NewDecoder(r.Body).Decode(&dateRange); err != nil {
			http.Error(w, fmt.Sprintf("Invalid JSON: %v", err), http.StatusBadRequest)
			return
		}

		// Parse the input dates (expecting RFC3339 format)
		startDate, err := time.Parse(time.RFC3339, dateRange.StartDate)
		if err != nil {
			http.Error(w, fmt.Sprintf("Invalid start date format: %v. Expected RFC3339 format (e.g., 2024-01-15T00:00:00Z)", err), http.StatusBadRequest)
			return
		}
		endDate, err := time.Parse(time.RFC3339, dateRange.EndDate)
		if err != nil {
			http.Error(w, fmt.Sprintf("Invalid end date format: %v. Expected RFC3339 format (e.g., 2024-01-15T23:59:59Z)", err), http.StatusBadRequest)
			return
		}

		if endDate.Before(startDate) {
			http.Error(w, "End date must be after start date", http.StatusBadRequest)
			return
		}

		// Log the query parameters
		log.Printf("Date range query: Start=%v (UTC), End=%v (UTC), Span=%.2f days",
			startDate.Format(time.RFC3339),
			endDate.Format(time.RFC3339),
			endDate.Sub(startDate).Hours()/24)

		// Query data for the specified date range
		// Use >= and <= to include both start and end dates
		sqlStmt := `
			SELECT temperature, humidity, pressure, gas_resistance, aqi, timestamp 
			FROM temp 
			WHERE timestamp >= ? AND timestamp <= ?
			ORDER BY timestamp ASC`

		rows, err := db.Query(sqlStmt, startDate.Format(time.RFC3339), endDate.Format(time.RFC3339))
		if err != nil {
			log.Printf("Database error: %v", err)
			http.Error(w, fmt.Sprintf("Database error: %v", err), http.StatusInternalServerError)
			return
		}
		defer rows.Close()

		var results []map[string]interface{}
		rowCount := 0
		for rows.Next() {
			var temperature, humidity, pressure float64
			var gasResistance, aqi sql.NullInt64
			var timestampStr string

			if err := rows.Scan(&temperature, &humidity, &pressure, &gasResistance, &aqi, &timestampStr); err != nil {
				log.Printf("Row scan error: %v", err)
				continue
			}

			// Parse timestamp
			timestamp, err := time.Parse(time.RFC3339, timestampStr)
			if err != nil {
				log.Printf("Timestamp parse error: %v", err)
				continue
			}

			result := map[string]interface{}{
				"temperature": temperature,
				"humidity":    humidity,
				"pressure":    pressure,
				"timestamp":   timestamp.Format(time.RFC3339),
			}

			if gasResistance.Valid {
				result["gas_resistance"] = gasResistance.Int64
			}

			if aqi.Valid {
				result["aqi"] = aqi.Int64
			}

			results = append(results, result)
			rowCount++
		}

		if err = rows.Err(); err != nil {
			log.Printf("Rows error: %v", err)
			http.Error(w, fmt.Sprintf("Database error: %v", err), http.StatusInternalServerError)
			return
		}

		log.Printf("Date range query returned %d rows", rowCount)
		if rowCount > 0 {
			firstTimestamp, _ := time.Parse(time.RFC3339, results[0]["timestamp"].(string))
			lastTimestamp, _ := time.Parse(time.RFC3339, results[len(results)-1]["timestamp"].(string))
			log.Printf("  First record: %v (UTC)", firstTimestamp.Format(time.RFC3339))
			log.Printf("  Last record: %v (UTC)", lastTimestamp.Format(time.RFC3339))
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(results)
	})

	// Health check endpoint
	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{
			"status": "healthy",
			"time":   time.Now().UTC().Format(time.RFC3339),
		})
	})

	// Get server port from environment or use default
	port := os.Getenv("PORT")
	if port == "" {
		port = "8811"
	}

	log.Printf("Server starting on port %s...", port)
	log.Printf("Health check: http://localhost:%s/health", port)
	log.Fatal(http.ListenAndServe(":"+port, nil))
}
