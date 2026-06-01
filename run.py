from waitress import serve
from app import create_app

app = create_app()

if __name__ == '__main__':
    print("Starting with waitress on port 5001...")
    serve(app, host='0.0.0.0', port=5001, threads=16)
