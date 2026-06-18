import keyboard
import time
import sys

print("Testing Num Lock hook and key simulation...")
print("Press ESC to exit.")

def on_numlock():
    print("Num Lock pressed!")
    # Try sending 'm' key press
    try:
        print("Sending 'm' press/release...")
        keyboard.press("m")
        time.sleep(0.05)
        keyboard.release("m")
        print("Sent!")
    except Exception as e:
        print(f"Error sending: {e}")

keyboard.add_hotkey("num lock", on_numlock, suppress=False)

# Keep running until Esc is pressed
keyboard.wait("esc")
print("Exiting test.")
