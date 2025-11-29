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

2. **Configure WiFi, Backend, Port, and Data Interval:**
   Edit `wifi.json`:
   ```json
   {
     "ssid": "YourWiFiNetwork",
     "password": "YourPassword",
     "backend_url": "http://your-server-ip:8811/temprec",
     "port": 8811,
     "data_interval": 300
   }
   ```
   
   **Important:** Replace the placeholder values with your actual:
   - WiFi network name (SSID)
   - WiFi password
   - Backend server URL (where you want to send sensor data)
   - Port: Server port number (default: 8811)
     - The port in `backend_url` will be overridden by this value if specified
     - Must be between 1 and 65535
   - Data interval: Time in seconds between readings (minimum: 60 seconds)
     - `300` = 5 minutes (default)
     - `600` = 10 minutes
     - `1800` = 30 minutes
     - `3600` = 1 hour

4. **Run:**
   The firmware will start automatically on boot if `main.py` is the main file.

## Features

- ✅ **Power-efficient** - Deep sleep mode for battery operation (~10µA in sleep)
- ✅ **Battery optimized** - WiFi disconnected after data transmission
- ✅ **Robust error handling** - Retries for sensor reads and HTTP requests
- ✅ **WiFi reconnection** - Automatically reconnects if WiFi drops
- ✅ **Data validation** - Checks sensor readings are within valid ranges
- ✅ **Memory management** - Garbage collection to prevent memory issues
- ✅ **Detailed logging** - Clear status messages for debugging
- ✅ **Gas resistance** - BME680 includes gas sensor (air quality)
- ✅ **Auto-reset** - Resets device if critical errors occur

## Power Management & Battery Operation

This firmware is optimized for battery-powered operation using ESP32 deep sleep mode.

### Power Consumption

- **Active mode**: ~80-150mA (when awake, reading sensor, WiFi connected)
- **Deep sleep mode**: ~10µA (between readings)
- **Typical cycle**: Wakes up → Reads sensor → Connects WiFi → Sends data → Disconnects WiFi → Deep sleep

### Battery Life Estimation

With a 2000mAh battery and 5-minute intervals:
- **Active time per cycle**: ~5-10 seconds
- **Sleep time per cycle**: ~290 seconds
- **Average current**: ~2-3mA
- **Estimated battery life**: ~30-40 days

To extend battery life:
- Increase `DATA_INTERVAL` (e.g., 600 seconds = 10 minutes)
- Ensure strong WiFi signal (faster connection = less power)
- Use a larger battery capacity

### Power Configuration

**Data Interval** (in `wifi.json`):
```json
{
  "data_interval": 300
}
```
- Time in seconds between sensor readings
- Minimum: 60 seconds (1 minute)
- Default: 300 seconds (5 minutes)
- Longer intervals = better battery life

**Advanced Settings** (in `main.py`):
```python
# Power management
USE_DEEP_SLEEP = True  # Set to False to disable deep sleep (for debugging)
DISCONNECT_WIFI_AFTER_SEND = True  # Disconnect WiFi after sending to save power

# Timeouts
BACKEND_TIMEOUT = 10  # HTTP timeout
WIFI_CONNECT_TIMEOUT = 30  # WiFi connection timeout
```

### Battery Setup Recommendations

1. **Battery Selection**:
   - Use a 3.7V Li-ion or LiPo battery (2000mAh+ recommended)
   - Add a voltage regulator if needed (ESP32 needs 3.3V)
   - Consider a TP4056 charging module for rechargeable batteries

2. **Power Supply**:
   - ESP32 can run directly from 3.3V or use onboard regulator (if available)
   - Ensure stable power during WiFi transmission (high current draw)

3. **Hardware Modifications** (Optional):
   - Remove power LED if present (saves ~1-2mA)
   - Use external pull-up resistors instead of internal (slightly lower power)
   - Consider using a low-dropout regulator (LDO) for better efficiency

4. **Testing**:
   - Set `USE_DEEP_SLEEP = False` initially to test functionality
   - Monitor serial output to verify operation
   - Once working, enable deep sleep for battery operation

## Configuration Options

### WiFi Configuration (`wifi.json`)

All user-configurable settings are in `wifi.json`:

```json
{
  "ssid": "YourWiFiNetwork",
  "password": "YourPassword",
  "backend_url": "http://your-server-ip:8811/temprec",
  "port": 8811,
  "data_interval": 300
}
```

- **backend_url**: Full URL to the backend server endpoint
  - Example: `"http://192.168.1.100:8811/temprec"`
  - The port in this URL will be overridden by the `port` field if specified

- **port**: Server port number (optional)
  - Default: 8811
  - Range: 1-65535
  - If specified, this port will replace the port in `backend_url`
  - Useful for easily changing the port without editing the full URL

- **data_interval**: Time in seconds between sensor readings
  - Minimum: 60 seconds (1 minute)
  - Default: 300 seconds (5 minutes)
  - Longer intervals = better battery life
  - Examples: 300 (5 min), 600 (10 min), 1800 (30 min), 3600 (1 hour)

### Advanced Settings (`main.py`)

For advanced users, these can be modified in `main.py`:

```python
# Power management
USE_DEEP_SLEEP = True  # Enable deep sleep for battery operation
DISCONNECT_WIFI_AFTER_SEND = True  # Disconnect WiFi after sending data

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

### Battery/Power Issues
- **Device not waking up**: Check battery voltage (should be >3.0V)
- **Short battery life**: Increase `DATA_INTERVAL` to reduce wake frequency
- **WiFi connection fails**: Ensure strong signal (weak signal = more power)
- **Deep sleep not working**: Set `USE_DEEP_SLEEP = False` to debug
- **Serial monitor not working**: Deep sleep resets the device; use a separate power source for debugging

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

