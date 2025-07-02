# dsiserialport.py

import serial

class DSISerialPort:
    def __init__(self, serial_port_com, error_function):
        self._serial_port_dsi = None
        self._serial_port_com = serial_port_com
        self._baud_rate = 9600
        self._error_function = error_function
        self.eeg_not_available = False

    def initialize_serial_port(self):
        try:
            self._serial_port_dsi = serial.Serial(self._serial_port_com, self._baud_rate, timeout=1)
            self.eeg_not_available = True
        except Exception as error:
            self._error_function('Error', f'Could not open serial port: {self._serial_port_com}: {error}')

    def send_signal(self, data):
        if self._serial_port_dsi:
            data_byte = data.to_bytes(1, 'big')
            try:
                self._serial_port_dsi.write(data_byte)
            except Exception as error:
                self._error_function(f'Error: cannot send data: {error}')

    def close_serial_port(self):
        if self._serial_port_dsi and self._serial_port_dsi.is_open:
            self._serial_port_dsi.close()
            pass