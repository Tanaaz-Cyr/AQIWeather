# Improved Backend - Weather Monitoring System

Enhanced backend server with improved timezone handling, better error management, and BME680 support.

## Improvements Over Original Backend

### 1. **Fixed Timezone Handling**
- Proper UTC to IST conversion
- Consistent timestamp handling across all endpoints
- Correct date range queries for IST timezone

### 2. **BME680 Support**
- Added `gas_resistance` field to database schema
- Backward compatible with BME280 (gas_resistance is optional)
- Gas resistance statistics and charts

### 3. **Better Error Handling**
- Input validation for sensor data ranges
- Clear error messages
- Proper HTTP status codes
- Database error logging

### 4. **Enhanced Database**
- Indexed timestamp column for better query performance
- Nullable gas_resistance field
- Automatic schema migration

### 5. **Improved API Responses**
- Consistent JSON format
- Better error messages
- Health check endpoint

## Database Schema

```sql
CREATE TABLE temp (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    temperature REAL NOT NULL,
    humidity REAL NOT NULL,
    pressure REAL NOT NULL,
    gas_resistance INTEGER,  -- BME680 specific, nullable
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_timestamp ON temp(timestamp);
```

## API Endpoints

All endpoints are the same as the original backend, with these improvements:

### POST /temprec
- **New:** Validates data ranges
- **New:** Supports gas_resistance field
- **Improved:** Better error messages

### GET /temp
- **New:** Returns gas_resistance if available
- **Improved:** Proper timestamp parsing

### POST /tempstat
- **New:** Includes gas_resistance statistics
- **Fixed:** Correct IST timezone handling

### POST /tempget
- **New:** Includes gas_resistance in CSV
- **Fixed:** Timestamps displayed in IST

### POST /tempdaterange
- **New:** Includes gas_resistance in results
- **Fixed:** Proper date range validation
- **Improved:** Better error handling

### GET /health (NEW)
- Health check endpoint
- Returns server status and current time

## Setup

1. **Install dependencies:**
   ```bash
   cd "Improved Backend"
   go mod download
   ```

2. **Run server:**
   ```bash
   go run main.go
   ```

3. **Or build:**
   ```bash
   go build -o weather-server main.go
   ./weather-server
   ```

## Configuration

The server uses port 8811 by default. To change:

```bash
export PORT=8080
go run main.go
```

Or modify the code in `main.go`:
```go
port := "8080"  // Change default port
```

## Migration from Original Backend

The improved backend is backward compatible. Existing databases will automatically get the `gas_resistance` column added (if it doesn't exist).

To migrate:
1. Stop the old backend
2. Start the improved backend
3. The schema will be updated automatically

## Features

- ✅ Proper timezone handling (UTC storage, IST display)
- ✅ BME680 gas resistance support
- ✅ Input validation
- ✅ Better error messages
- ✅ Performance improvements (indexed queries)
- ✅ Health check endpoint
- ✅ Backward compatible with BME280 data

## Frontend

The improved frontend (`index.html`) includes:
- Modern, responsive UI
- Fixed timezone display (proper IST conversion)
- Gas resistance charts and statistics
- Better chart rendering with Chart.js
- Improved error handling
- Auto-refresh of current values

## Testing

Test the health endpoint:
```bash
curl http://localhost:8811/health
```

Test data recording:
```bash
curl -X POST http://localhost:8811/temprec \
  -H "Content-Type: application/json" \
  -d '{"temperature":23.45,"humidity":56.78,"pressure":1013.25,"gas_resistance":123456}'
```

## Troubleshooting

### Database Errors
- Check file permissions on `data.db`
- Ensure SQLite3 is properly installed
- Check disk space

### Timezone Issues
- All timestamps are stored in UTC
- Frontend converts to IST for display
- Backend queries convert IST dates to UTC

### Gas Resistance Not Showing
- Ensure firmware is sending `gas_resistance` field
- Check database has the column: `PRAGMA table_info(temp);`
- Verify data is being recorded with gas_resistance

