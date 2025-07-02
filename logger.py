import os
from datetime import datetime
from tkinter.scrolledtext import ScrolledText

class Logger:
    def __init__(self, log_dir: str = "c:\\eeg\\PilotHoldingTask\\Log"):
        """Initialize the Logger class with a custom log directory and set up the log file."""
        # Create log directory if it doesn't exist
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)

        # Generate log file name with timestamp
        self._timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(self.log_dir, f"log_{self._timestamp}.txt")
        self.log_gnss_file = os.path.join(self.log_dir, f"log_{self._timestamp}.txt")

        # Initialize optional log display attribute
        self.log_display = None


    def get_filename_timestamp(self):
        return self._timestamp

    def set_log_display(self, log_display: ScrolledText):
        """Set the log display widget for GUI applications."""
        self.log_display = log_display

    def log(self, message: str, level: str = "INFO"):
        """Log a message with a specified level to the log file and print it to the console."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_message = f"{timestamp} [{level}] - {message}\n"

        # Write to log file
        with open(self.log_file, 'a') as file:
            file.write(log_message)

        # Print to console
        print(log_message, end='')  # Avoid extra newline in console output

        # Display in log display widget if set
        if self.log_display:
            self.log_display.config(state='normal')
            self.log_display.insert('end', log_message)
            self.log_display.yview('end')
            self.log_display.config(state='disabled')

    def log_click(self, button_text: str):
        """Log a button click action with specific details."""
        self.log(f"Button clicked: {button_text}", level="ACTION")

    def log_signal(self, signal: str):
        """Log a signal sent to the EEG device."""
        self.log(f"Signal sent: {signal}", level="SIGNAL")

    def log_generated_text(self, text: str):
        """Log generated text or output for reference."""
        self.log(f"Generated text: {text}", level="OUTPUT")

    def clear_log_display(self):
        """Clear the log display widget, if it is set."""
        if self.log_display:
            self.log_display.config(state='normal')
            self.log_display.delete('1.0', 'end')
            self.log_display.config(state='disabled')
