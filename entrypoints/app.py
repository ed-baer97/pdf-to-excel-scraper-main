from webapp import create_app

app = create_app()

if __name__ == "__main__":
    # ВАЖНО: use_reloader=False чтобы фоновые потоки скрапера не убивались
    # При изменении кода нужно перезапустить вручную (Ctrl+C, python app.py)
    app.run(host="127.0.0.1", port=5000, use_reloader=False)

