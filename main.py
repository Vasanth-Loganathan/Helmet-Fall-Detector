import network
import urequests
import time  # Changed from utime to time
from machine import Pin, I2C, ADC, UART


# MPU6050 Definition
class MPU6050:
    def __init__(self, i2c, addr=0x68):
        """
        Initializes the MPU6050 sensor.

        Args:
            i2c: The I2C object.
            addr: The I2C address of the MPU6050.
        """
        self.i2c = i2c
        self.addr = addr
        try:
            self.i2c.writeto_mem(self.addr, 0x6B, b'\x00')  # Wake up the MPU6050
        except Exception as e:
            print(f"Error initializing MPU6050: {e}")
            self.initialized = False
            return
        self.initialized = True

    def read_raw_data(self, reg):
        """
        Reads raw data from the MPU6050.

        Args:
            reg: The register address to read from.

        Returns:
            The raw data (16-bit signed integer).
        """
        if not self.initialized:
            return 0
        data = self.i2c.readfrom_mem(self.addr, reg, 2)
        val = int.from_bytes(data, 'big')
        return val - 65536 if val > 32768 else val

    def get_accel_data(self):
        """
        Gets the accelerometer data from the MPU6050.

        Returns:
            A dictionary containing the x, y, and z accelerometer values in g, or None on error.
        """
        if not self.initialized:
            return None
        try:
            ax = self.read_raw_data(0x3B) / 16384.0
            ay = self.read_raw_data(0x3D) / 16384.0
            az = self.read_raw_data(0x3F) / 16384.0
            return {'x': ax, 'y': ay, 'z': az}
        except Exception as e:
            print(f"Error reading accelerometer data: {e}")
            return None

    def get_gyro_data(self):
        """
        Gets the gyroscope data from the MPU6050.

        Returns:
            A dictionary containing the x, y, and z gyroscope values in degrees per second, or None on error.
        """
        if not self.initialized:
            return None
        try:
            gx = self.read_raw_data(0x43) / 131.0
            gy = self.read_raw_data(0x45) / 131.0
            gz = self.read_raw_data(0x47) / 131.0
            return {'x': gx, 'y': gy, 'z': gz}
        except Exception as e:
            print(f"Error reading gyroscope data: {e}")
            return None


def get_time_from_google():
    """
    Gets the current time from Google's HTTP headers and converts it to IST.
    Handles errors.

    Returns:
        A timestamp (seconds since epoch) on success, None on failure.
    """
    try:
        response = urequests.get("http://www.google.com")
        date_str = response.headers.get("Date")  # 'Thu, 15 May 2025 10:25:39 GMT'
        response.close()
        time.sleep(2)
        if not date_str:
            print("Failed to get date from headers.")
            return None

        

        # Parse date string
        months = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                  'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}
        parts = date_str.split()
        day = int(parts[1])
        month = months[parts[2]]
        year = int(parts[3])
        h, m, s = map(int, parts[4].split(":"))

        # Convert to seconds since epoch (UTC)
        utc_tuple = (year, month, day, h, m, s, 0, 0)
        utc_seconds = time.mktime(utc_tuple)  # Use time.mktime

        # Add IST offset (5 hours 30 minutes = 19800 seconds)
        ist_seconds = utc_seconds + 19800
        return ist_seconds
    except Exception as e:
        print("Error getting time from Google:", e)
        return None



# WiFi and Telegram
SSID = "WIFI provider name"
PASSWORD = "password"
BOT_TOKEN = "botToken"  # Replace with your bot token
CHAT_ID = 6046574860

# Thresholds and GPIO Setup
ACC_THRESHOLD = 1
GYRO_THRESHOLD = 1
SOUND_THRESHOLD = 1000
GPS_TIMEOUT = 10
BUZZER_DURATION = 4

buzzer = Pin(15, Pin.OUT)
# Sensor Setup
i2c = I2C(0, scl=Pin(1), sda=Pin(0))
mpu = MPU6050(i2c)
mic = ADC(26)
gps_uart = UART(1, baudrate=9600, tx=Pin(4), rx=Pin(5))

bike_start_time = None
fall_detected = False
is_wifi_connected = False



def connect_wifi(ssid, password):
    """
    Connects to WiFi.  Does NOT get the time.

    Args:
        ssid: The WiFi SSID.
        password: The WiFi password.

    Returns:
        True on success, False on failure.
    """
    global is_wifi_connected
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('Connecting to WiFi...')
        wlan.connect(ssid, password)
        for _ in range(20):
            if wlan.isconnected():
                break
            time.sleep(0.5)
    if wlan.isconnected():
        print("Connected:", wlan.ifconfig())
        is_wifi_connected = True
        return True
    else:
        print("WiFi connection failed")
        is_wifi_connected = False
        return False



def send_telegram_alert(bot_token, chat_id, message):
    """
    Sends a Telegram alert message.

    Args:
        bot_token: The Telegram bot token.
        chat_id: The Telegram chat ID.
        message: The message to send.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = f"chat_id={chat_id}&text={message}"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        response = urequests.post(url, data=payload, headers=headers)
        print("Telegram response:", response.text)
        response.close()
    except Exception as e:
        print("Error sending message:", e)



def convert_to_degrees(raw):
    """Converts raw GPS coordinates to degrees.

    Args:
        raw: The raw GPS coordinate string.

    Returns:
        The coordinate in degrees, or None on error.
    """
    try:
        if not raw or len(raw) < 5:
            return None
        degrees = int(raw[:2])
        minutes = float(raw[2:]) / 60.0
        return degrees + minutes
    except Exception as e:
        print("Convert error:", e)
        return None



def get_gps_location(timeout=GPS_TIMEOUT):
    """
    Gets the GPS location.

    Args:
        timeout: The timeout in seconds.

    Returns:
        A tuple containing the latitude and longitude, or None on failure.
    """
    gps_uart.read()
    start = time.time()  # Use time
    while time.time() - start < timeout:  # Use time
        if gps_uart.any():
            line = gps_uart.readline()
            if line and b"GPGGA" in line:
                try:
                    parts = line.decode().strip().split(",")
                    if len(parts) > 5 and parts[2] and parts[4]:
                        lat = convert_to_degrees(parts[2])
                        lon = convert_to_degrees(parts[4])
                        if lat is not None and lon is not None:
                            if parts[3] == 'S':
                                lat = -lat
                            if parts[5] == 'W':
                                lon = -lon
                            return (lat, lon)
                except Exception as e:
                    print(f"Error processing GPS data: {e}, line: {line}")
    return None



def on_buzzer():
    """Activates the buzzer."""
    for _ in range(10):
        buzzer.value(1)
        time.sleep(BUZZER_DURATION)  # Use time
        buzzer.value(0)
        time.sleep(BUZZER_DURATION)  # Use time



def check_conditions():
    """
    Checks if fall conditions are met based on accelerometer, gyroscope, and sound sensor data.

    Returns:
        A tuple containing:
            - True if fall conditions are met, False otherwise.
            - The acceleration magnitude.
            - The gyroscope magnitude.
            - The sound level.
    """
    acc = mpu.get_accel_data()
    gyro = mpu.get_gyro_data()
    if not acc or not gyro:
        return False, 0, 0, 0
    acc_mag = (acc['x'] ** 2 + acc['y'] ** 2 + acc['z'] ** 2) ** 0.5 * 9.8
    gyro_mag = (gyro['x'] ** 2 + gyro['y'] ** 2 + gyro['z'] ** 2) ** 0.5
    try:
        sound = mic.read_u16()
    except Exception as e:
        print(f"Error reading microphone data: {e}")
        sound = 0
    print(f"Accel: {acc_mag:.2f}, Gyro: {gyro_mag:.2f}, Sound: {sound}")
    all_met = acc_mag > ACC_THRESHOLD and gyro_mag > GYRO_THRESHOLD and sound > SOUND_THRESHOLD
    return all_met, acc_mag, gyro_mag, sound



def is_bike_on():
    """
    Checks if the bike is on (simulated by WiFi connection).  Gets the time from Google if available.

    Returns:
        True if the bike is on, False otherwise.
    """
    global bike_start_time, is_wifi_connected
    if not is_wifi_connected:
        is_wifi_connected = connect_wifi(SSID, PASSWORD)  # Connect only, no time here

    if not is_wifi_connected:
        print("Connect the Fall Detector to WiFi to start the Bike")
        return False

    # Get time when bike is turned on
    initial_time = get_time_from_google()
    if initial_time is None:
        print("Failed to get time at bike start. Time will be inaccurate.")
        bike_start_time = None # Set to None to indicate no time.
    else:
        bike_start_time = initial_time

    return True



def format_time(timestamp):
    """Formats a timestamp into a human-readable string.

    Args:
        timestamp: The timestamp (seconds since epoch).

    Returns:
        A formatted time string.
    """
    local_time = time.localtime(timestamp)  # Use time
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        local_time[0], local_time[1], local_time[2],
        local_time[3], local_time[4], local_time[5]
    )



# Main loop
while True:
    if is_bike_on():
        met, acc, gyro, snd = check_conditions()
        if met:
            if not fall_detected:
                fall_detected = True
                loc = get_gps_location()

                # Get time when fall is detected
                fall_time = get_time_from_google()
                if fall_time is None:
                    print("Failed to get time at fall.")
                    fall_time = None # Set to None
                

                location_string = "Unknown"
                if loc:
                    lat, lon = loc
                lat = 11.0245
                lon = 77.00025
                location_string = f"http://maps.google.com/?q={lat},{lon}"
                msg = "Helmet Fall Detected!\n"
                if bike_start_time:
                    start_time_str = format_time(bike_start_time)
                    msg += f"Bike Start Time: {start_time_str}\n"
                if fall_time:
                    fall_time_str = format_time(fall_time)
                    msg += f"Fall Detected Time: {fall_time_str}\n"
                msg += (
                    f"Bike Fall Detected"
                    f"Location: {location_string}\n"
                    f"Acceleration: {acc:.2f} m/s^2\n"  # Include sensor data in message
                    f"Gyroscope: {gyro:.2f} deg/s\n"
                    f"Sound: {snd}\n"
                )
                print("Fall Detected")
                send_telegram_alert(BOT_TOKEN, CHAT_ID, msg)
                on_buzzer()
                time.sleep(15)
        else:
            cur_time = get_time_from_google()
            cur_time = format_time(cur_time)
            print("Current Time:",cur_time)
            print("Conditions not met.")
            
        time.sleep(2)
