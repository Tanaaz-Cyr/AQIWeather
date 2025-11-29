# BME680 Library Usage

This firmware uses the **pimoroni bme680-python** library for accurate sensor readings.

## Files Required

1. **main_bme680_lib.py** - Main firmware using the external library
2. **micropython_smbus2.py** - MicroPython adapter for smbus2 interface
3. **lib/** folder containing:
   - `bme680/` - BME680 library
   - `smbus2/` - SMBus2 library (not used directly, but needed for imports)

## Upload Instructions

1. Upload the entire `lib/` folder to your ESP32 at `/lib/`
2. Upload `micropython_smbus2.py` to the root of your ESP32
3. Upload `main_bme680_lib.py` as `main.py` to your ESP32
4. Upload `wifi.json` with your WiFi credentials

## How It Works

The `micropython_smbus2.py` adapter makes MicroPython's I2C interface compatible with the smbus2 interface that the bme680 library expects. The library uses proper calibration data reading and compensation formulas from Bosch.

## Advantages

- ✅ Uses proven, tested library with correct calibration
- ✅ Proper temperature, pressure, humidity, and gas resistance calculations
- ✅ Handles both BME680 variants (low and high gas resistance)
- ✅ Automatic sensor configuration
- ✅ Proper gas heater control

## Usage

The library automatically:
- Detects the sensor at 0x76 or 0x77
- Loads calibration data correctly
- Configures oversampling and filters
- Handles gas sensor heating
- Provides accurate compensated readings

## Example Output

```
BME680 detected at address 0x76
BME680 sensor initialized successfully
Reading sensor...
  Temperature: 27.5°C
  Humidity: 45.2%
  Pressure: 996.5hPa
  Gas Resistance: 3257216Ω
  AQI: 0
```

## Troubleshooting

If you get import errors:
- Make sure `lib/bme680/` and `lib/smbus2/` are uploaded
- Check that `micropython_smbus2.py` is in the root directory
- Verify the file structure matches the expected paths

If readings are still wrong:
- Check I2C connections (SCL=GPIO22, SDA=GPIO21)
- Verify sensor is powered with 3.3V
- Check I2C address (0x76 or 0x77)

