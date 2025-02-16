from flask import Flask, request, jsonify
import json
from datetime import datetime
import os

app = Flask(__name__)

# Create a data directory if it doesn't exist
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
os.makedirs(DATA_DIR, exist_ok=True)

@app.route('/api/data', methods=['POST'])
def receive_data():
    try:
        # Get JSON data from request
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'data_{timestamp}.json'
        file_path = os.path.join(DATA_DIR, filename)
        
        # Save data to file
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        timestamp = datetime.now().isoformat()

        return jsonify({
            'message': 'Data saved successfully',
            'filename': filename,
            'timestamp': timestamp
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
