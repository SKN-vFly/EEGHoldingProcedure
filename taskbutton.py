# taskbutton.py
import tkinter as tk

class TaskButton:
    def __init__(
        self,
        parent,
        row,
        column,
        text,
        command,
        logger,
        width=15,
        height=2
    ):
        # Zapisujemy podany callback w atrybucie self.callback
        self.callback = command
        self.logger = logger

        # Przycisk Tkinter, którego "command" ustawiamy na metodę on_click
        self.button = tk.Button(
            parent,
            text=text,
            command=self.on_click,  # Używamy on_click, aby wywołać self.callback
            width=width,
            height=height
        )
        self.button.grid(row=row, column=column, padx=5, pady=5)

    def on_click(self):
        """
        Metoda wywoływana po kliknięciu w przycisk.
        Logujemy kliknięcie (jeżeli logger istnieje) i wywołujemy self.callback(),
        czyli faktyczną funkcję związaną z danym przyciskiem.
        """
        if self.logger:
            self.logger.log_click(self.button.cget("text"))
        if self.callback:
            self.callback()

    def update_button(self, new_text, new_command, bg=None):
        """
        Zmiana etykiety i callbacku przycisku w trakcie działania programu.
        Zamiast przypisywać direct w button.config(...),
        przechowujemy nowy callback także w self.callback.
        """
        self.callback = new_command
        self.button.config(text=new_text, command=self.on_click)

        if bg:
            self.button.config(bg=bg)
        else:
            self.button.config(bg='SystemButtonFace')  # Przywróć domyślny kolor

    def show(self):
        self.button.grid()

    def hide(self):
        self.button.grid_remove()

    def place(self, relx, rely):
        self.button.place(relx=relx, rely=rely)

    def is_visible(self):
        return self.button.winfo_viewable()
