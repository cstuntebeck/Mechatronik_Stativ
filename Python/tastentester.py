import tkinter as tk
def taste(event):
    print(f"Taste gedrückt: {event.keysym}")
root = tk.Tk()
root.bind("<Key>", taste)
root.mainloop()
