import sys

def main() -> int:
    # If run with --core, we launch the bot
    if "--core" in sys.argv:
        from src import main as bot_main
        bot_main.run()
        return 0

    # Otherwise we launch the GUI
    from desktop_app.app import run_gui
    return run_gui()

if __name__ == "__main__":
    sys.exit(main())
