from app import create_app

app = create_app()

if __name__ == '__main__':
    try:
        from waitress import serve
        print("Starting with waitress (production server)...")
        serve(app, host='0.0.0.0', port=5000, threads=16)
    except ImportError:
        print("waitress not installed, falling back to Flask dev server")
        print("Run: pip install waitress")
        app.run(host='0.0.0.0', debug=False, threaded=True)
