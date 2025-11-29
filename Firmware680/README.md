# BME680 Firmware - ESP32 Weather Monitoring

Improved firmware for BME680 sensor with enhanced stability and error handling.

## Pin Configuration

**Use these pins on your ESP32:**

| BME680 Pin | ESP32 Pin | Description |
|------------|-----------|-------------|
| VCC        | 3.3V      | Power (3.3V only!) |
| GND        | GND       | Ground |
| SCL        | **GPIO 22** | I2C Clock |
| SDA        | **GPIO 21** | I2C Data |

### Why These Pins?

- **GPIO 21 (SDA)** and **GPIO 22 (SCL)** are the default I2C pins on ESP32
- These pins have built-in pull-up resistors on most ESP32 boards
- They are the most stable and recommended I2C pins
- Compatible with all ESP32 variants

### Alternative Pins (if needed)

If GPIO 21/22 are not available, you can modify `main.py`:
```python
I2C_SCL_PIN = 19  # Alternative SCL pin
I2C_SDA_PIN = 18  # Alternative SDA pin
```

**Note:** If using alternative pins, ensure they support I2C functionality.

## Setup Instructions

1. **Upload files to ESP32:**
   - `bme680.py` - Sensor driver
   - `main.py` - Main firmware
   - `wifi.json` - WiFi credentials

2. **Configure WiFi and Backend:**
   Edit `wifi.json`:
   ```json
   {
     "ssid": "YourWiFiNetwork",
     "password": "YourPassword",
     "backend_url": "http://your-server-ip:8811/temprec"
   }
   ```
   
   **Important:** Replace the placeholder values with your actual:
   - WiFi network name (SSID)
   - WiFi password
   - Backend server URL (where you want to send sensor data)

4. **Run:**
   The firmware will start automatically on boot if `main.py` is the main file.

## Features

- ✅ **Robust error handling** - Retries for sensor reads and HTTP requests
- ✅ **WiFi reconnection** - Automatically reconnects if WiFi drops
- ✅ **Data validation** - Checks sensor readings are within valid ranges
- ✅ **Memory management** - Garbage collection to prevent memory issues
- ✅ **Detailed logging** - Clear status messages for debugging
- ✅ **Gas resistance** - BME680 includes gas sensor (air quality)
- ✅ **Auto-reset** - Resets device if critical errors occur

## Configuration Options

Edit these values in `main.py`:

```python
# Data collection interval (seconds)
DATA_INTERVAL = 300  # 5 minutes

# Retry settings
SENSOR_READ_RETRIES = 3
HTTP_RETRIES = 3
MAX_WIFI_RETRIES = 5

# Timeouts
BACKEND_TIMEOUT = 10  # HTTP timeout
WIFI_CONNECT_TIMEOUT = 30  # WiFi connection timeout
```

## Troubleshooting

### Sensor Not Detected
- Check I2C connections (especially power to 3.3V)
- Verify pins are GPIO 21 (SDA) and GPIO 22 (SCL)
- Check I2C address (should be 0x76 or 0x77)

### WiFi Connection Issues
- Verify SSID and password in `wifi.json`
- Ensure 2.4GHz network (ESP32 doesn't support 5GHz)
- Check signal strength

### HTTP Request Failures
- Verify backend server is running
- Check backend URL is correct
- Ensure firewall allows connections
- Check network connectivity

## Data Format

The firmware sends this JSON to the backend:
```json
{
  "temperature": 23.45,
  "humidity": 56.78,
  "pressure": 1013.25,
  "gas_resistance": 123456
}
```

## Differences from BME280 Firmware

1. **Gas Resistance** - BME680 includes air quality sensor
2. **Better Error Handling** - More robust retry logic
3. **WiFi Reconnection** - Automatic reconnection on disconnect
4. **Data Validation** - Checks sensor readings are valid
5. **Memory Management** - Garbage collection to prevent crashes
6. **Better Logging** - More detailed status messages

