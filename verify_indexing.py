import requests
import os

def test_indexing():
    url = "http://localhost:8000/index-policy"
    policy_id = "POL-TEST"
    
    file_path = "test_policy.pdf"
    with open(file_path, "w") as f:
        f.write("%PDF-1.4\n1 0 obj\n<< /Title (Test) >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF")
    
    try:
        with open(file_path, 'rb') as f:
            files = {
                'file': (file_path, f, 'application/pdf')
            }
            data = {
                'policy_id': policy_id
            }
            
            print(f"Sending request to {url}...")
            try:
                response = requests.post(url, files=files, data=data)
                print(f"Status: {response.status_code}")
                print(f"Response: {response.text}")
            except Exception as e:
                print(f"Error: {e}")
    finally:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error removing file: {e}")

if __name__ == "__main__":
    test_indexing()
