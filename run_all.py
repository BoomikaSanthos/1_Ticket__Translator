import subprocess
import sys
import time
import os
from pathlib import Path

def main():
    # Force working directory to the folder containing this script (project root)
    script_dir = Path(__file__).parent.resolve()
    os.chdir(str(script_dir))
    
    backend_dir = script_dir / "backend"
    
    # Check if dependencies are installed
    try:
        import flask
        import flask_cors
        import requests
        import deep_translator
        import langdetect
    except ImportError:
        print("Required dependencies not found. Installing...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "backend/requirements.txt"])
        except Exception as e:
            print(f"Failed to install requirements via requirements.txt: {e}")
            print("Trying direct pip install...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "flask", "flask-cors", "requests"])
    
    processes = []
    try:
        # Start Module 1 (Translator)
        print("Starting Module 1 (Translator) on port 5001...")
        p1 = subprocess.Popen(
            [sys.executable, "module1_translator.py"],
            cwd=str(backend_dir)
        )
        processes.append(p1)
        
        # Start Module 2 (Ticket Manager)
        print("Starting Module 2 (Ticket Manager) on port 5002...")
        p2 = subprocess.Popen(
            [sys.executable, "module2_ticket_manager.py"],
            cwd=str(backend_dir)
        )
        processes.append(p2)
        
        # Start Module 3 (Orchestrator)
        print("Starting Module 3 (Orchestrator) on port 5003...")
        p3 = subprocess.Popen(
            [sys.executable, "module3_orchestrator.py"],
            cwd=str(backend_dir)
        )
        processes.append(p3)
        
        print("\nAll services are starting up...")
        print("You can access the application at http://localhost:5003/\n")
        print("Press Ctrl+C to stop all services.")
        
        # Open in browser automatically
        time.sleep(3)  # Give them a moment to start
        import webbrowser
        print("Opening dashboard in browser...")
        webbrowser.open("http://localhost:5003/")
        
        while True:
            time.sleep(1)
            # Check if any process terminated
            for i, p in enumerate(processes):
                if p.poll() is not None:
                    print(f"Service {i+1} terminated unexpectedly with code {p.returncode}.")
                    raise KeyboardInterrupt
                    
    except KeyboardInterrupt:
        print("\nStopping all services...")
        for p in processes:
            try:
                p.terminate()
            except Exception:
                pass
        for p in processes:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
        print("All services stopped.")

if __name__ == "__main__":
    main()
