import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'

    if debug:
        app.run(host='0.0.0.0', port=5000, debug=True)
    else:
        try:
            from waitress import serve
            print("Starting with waitress on port 5000...")
            serve(app, host='0.0.0.0', port=5000, threads=16)
        except ImportError:
            print("waitress not installed. Run: pip install waitress")
            app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
