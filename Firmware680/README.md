# BME680 Firmware - ESP32 Weather Monitoring

Improved firmware for BME680 sensor with enhanced stability and error handling.

## Pin Configuration

**Use these pins on your ESP32:**

| BME680 Pin | ESP32 Pin | Description |
|------------|-----------|-------------|
| VCC        | **GPIO 4** or 3.3V | Power (see Power Control section) |
| GND        | GND       | Ground |
| SCL        | **GPIO 22** | I2C Clock |
| SDA        | **GPIO 21** | I2C Data |

### Why These Pins?

- **GPIO 21 (SDA)** and **GPIO 22 (SCL)** are the default I2C pins on ESP32
- These pins have built-in pull-up resistors on most ESP32 boards
- They are the most stable and recommended I2C pins
- Compatible with all ESP32 variants

### Sensor Power Control (Recommended)

**GPIO 4** is used for sensor power control to enable hardware reset when the sensor gets stuck. This is **highly recommended** for BME680 reliability.

**Option 1: Direct GPIO Power (Simplest)**
- Connect BME680 VCC directly to **GPIO 4**
- BME680 draws ~3.7mA, well within ESP32's 12mA recommended limit
- No additional components needed

**Option 2: MOSFET Switch (More Reliable)**
- Use a small N-channel MOSFET (e.g., 2N7000 or IRLZ44N)
- ESP32 GPIO 4 → MOSFET Gate
- ESP32 3.3V → MOSFET Drain → BME680 VCC
- ESP32 GND → MOSFET Source → BME680 GND

**To disable power control** (sensor always powered), set in `main.py`:
```python
SENSOR_POWER_PIN = None  # Disable power control
```

### Alternative Pins (if needed)

If GPIO 21/22 are not available, you can modify `main.py`:
```python
I2C_SCL_PIN = 19  # Alternative SCL pin
I2C_SDA_PIN = 18  # Alternative SDA pin
SENSOR_POWER_PIN = 5  # Alternative power control pin (must support 40mA)
```

**Note:** If using alternative pins, ensure they support I2C functionality. For power control, use pins that can source at least 12mA (GPIO 1, 2, 4, 5, 18, 19, 21, 22, 23).

## Setup Instructions

1. **Upload files to ESP32:**
   - `bme680.py` - Sensor driver
   - `main.py` - Main firmware
   - `wifi.json` - WiFi credentials

2. **Configure WiFi, Backend, Port, Data Interval, and Power Mode:**
   Edit `wifi.json`:
   ```json
   {
     "ssid": "YourWiFiNetwork",
     "password": "YourPassword",
     "backend_url": "http://your-server-ip:8811/temprec",
     "port": 8811,
     "data_interval": 300,
     "onBattery": false
   }
   ```
   
   **Important:** Replace the placeholder values with your actual:
   - **ssid**: WiFi network name
   - **password**: WiFi password
   - **backend_url**: Backend server URL (where you want to send sensor data)
   - **port**: Server port number (default: 8811)
     - The port in `backend_url` will be overridden by this value if specified
     - Must be between 1 and 65535
   - **data_interval**: Time in seconds between readings (minimum: 60 seconds)
     - `300` = 5 minutes (default)
     - `600` = 10 minutes
     - `1800` = 30 minutes
     - `3600` = 1 hour
   - **onBattery**: Power mode setting
     - `true` = Battery mode (uses deep sleep between readings)
     - `false` = AC power mode (keeps device awake, uses delay between readings)

4. **Run:**
   The firmware will start automatically on boot if `main.py` is the main file.

## Features

- ✅ **Power-efficient** - Deep sleep mode for battery operation (~10µA in sleep)
- ✅ **Battery optimized** - Configurable deep sleep or continuous operation
- ✅ **Hardware sensor reset** - GPIO-controlled power cycling for stuck sensors
- ✅ **Aggressive error recovery** - Any error triggers immediate recovery or reboot
- ✅ **Sensor timeout protection** - Prevents infinite hangs on I2C communication failures
- ✅ **WiFi reconnection** - Automatically reconnects if WiFi drops
- ✅ **Memory optimized** - Reduced code size and efficient memory usage
- ✅ **Detailed logging** - Clear status messages for debugging
- ✅ **Gas resistance** - BME680 includes gas sensor (air quality)
- ✅ **Auto-reboot on errors** - Prevents device from getting stuck in bad states
- ✅ **AP mode fallback** - Falls back to AP mode if WiFi connection fails

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
# I2C Configuration
I2C_SCL_PIN = 22  # I2C Clock pin
I2C_SDA_PIN = 21  # I2C Data pin
I2C_FREQ = 100000  # I2C frequency (100kHz)
BME680_ADDRESS = 0x76  # Sensor I2C address (0x76 or 0x77)

# Sensor Power Control
SENSOR_POWER_PIN = 4  # GPIO pin for sensor power control (None to disable)

# LED Configuration
LED_PIN = 2  # GPIO pin for status LED

# Timeouts
BACKEND_TIMEOUT = 10  # HTTP timeout (seconds)
WIFI_TIMEOUT = 30  # WiFi connection timeout (seconds)
```

**Note**: Most settings are now in `wifi.json` for easier configuration. Only modify `main.py` if you need to change hardware pin assignments.

## Troubleshooting

### Sensor Not Detected
- Check I2C connections (especially power)
- Verify pins are GPIO 21 (SDA) and GPIO 22 (SCL)
- Check I2C address (should be 0x76 or 0x77, default is 0x76)
- If using power control: Verify GPIO 4 is connected to sensor VCC
- Check that sensor power control is initialized (see serial output)

### Sensor Errors / Device Stops Working
- **Symptom**: Device stops sending data after a few hours
- **Solution**: Enable GPIO power control (connect sensor VCC to GPIO 4)
- The firmware will automatically power cycle the sensor on errors
- If power cycling doesn't help, device will reboot to recover
- Check serial output for specific error messages

### Sensor Timeout Errors
- **Symptom**: "BME680 sensor timeout - sensor not responding"
- **Causes**: I2C bus lockup, sensor stuck, loose connections
- **Solution**: 
  - Enable GPIO power control for automatic recovery
  - Check I2C wiring (SDA/SCL connections)
  - Verify power supply is stable
  - Check for I2C bus conflicts with other devices

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
  "gas_resistance": 123456,
  "aqi": 45
}
```

- **temperature**: Temperature in Celsius (°C)
- **humidity**: Relative humidity percentage (%)
- **pressure**: Atmospheric pressure in hectopascals (hPa)
- **gas_resistance**: Gas sensor resistance in ohms (Ω)
- **aqi**: Air Quality Index (calculated from gas resistance, 0-500)

## Known Issues & Solutions

### BME680 Sensor Stuck After Hours

**Problem**: Sensor stops responding after running for several hours, device stops sending data.

**Root Cause**: BME680 can get stuck in a bad state that persists through soft resets.

**Solution**: 
1. **Enable GPIO Power Control** (Recommended):
   - Connect BME680 VCC to GPIO 4 (or another GPIO pin)
   - Set `SENSOR_POWER_PIN = 4` in `main.py`
   - Firmware will automatically power cycle sensor on errors

2. **Hardware Reset**:
   - If GPIO power control not available, physically disconnect/reconnect sensor power
   - Or use a hardware reset circuit

**Why This Works**: Hardware power cycle completely resets the sensor's internal state, clearing any stuck conditions that soft resets can't fix.

## Error Handling & Recovery

### Sensor Error Recovery

The firmware includes multiple layers of error protection:

1. **I2C Timeout Protection**: 
   - BME680 library has 1-second timeout on sensor reads
   - Prevents infinite hangs if sensor stops responding

2. **Hardware Power Cycling**:
   - On sensor error, GPIO power control turns sensor off/on
   - Gives sensor a complete hardware reset
   - Attempts to read again before rebooting

3. **Automatic Reboot**:
   - If sensor error persists after power cycle, ESP32 reboots
   - Prevents device from getting stuck in bad state
   - Ensures fresh start on next boot

### Error Behavior

- **Sensor Error**: 
  - First: Attempt power cycle (if GPIO power control enabled)
  - If power cycle succeeds: Continue operation
  - If power cycle fails: Reboot ESP32 (3 LED blinks)

- **WiFi Error**: 
  - Falls back to AP mode for configuration
  - Allows WiFi reconfiguration via web interface

- **Any Other Error**: 
  - Immediate reboot (5 LED blinks)
  - Prevents device from hanging indefinitely

### LED Blink Codes

- **3 blinks**: Sensor error - power cycling or rebooting
- **5 blinks**: General error - rebooting ESP32
- **Continuous blink**: WiFi connection attempt
- **Solid ON**: AP mode active

## Differences from BME280 Firmware

1. **Gas Resistance** - BME680 includes air quality sensor
2. **Hardware Power Control** - GPIO-controlled sensor reset capability
3. **Timeout Protection** - Prevents infinite hangs on I2C failures
4. **Aggressive Error Recovery** - Power cycles sensor before rebooting
5. **Memory Optimized** - Reduced code size for better reliability
6. **Better Error Handling** - Multiple recovery mechanisms
7. **AP Mode Fallback** - Automatic fallback if WiFi fails
8. **Configurable Power Mode** - Battery (deep sleep) or AC (continuous) operation

