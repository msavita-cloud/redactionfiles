from flask import Flask, request, redirect, url_for
from werkzeug.utils import secure_filename
from azure.ai.textanalytics import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from azure.ai.formrecognizer import DocumentAnalysisClient
import os
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont
import io

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'

# Azure AI and Blob Storage configuration
# Azure AI and Blob Storage configuration
azure_ai_key = ''
azure_ai_endpoint = 'https://xxxx.openai.azure.com/'
blob_connection_string = 'DefaultEndpointsProtocol=https;AccountName=xxx;AccountKey=xxxxx/xxx;EndpointSuffix=core.windows.net'
blob_container_name = 'redactedfiles'
form_recognizer_key = 'xxxx'
form_recognizer_endpoint = 'https://xxx-reocg.cognitiveservices.azure.com/'

# Initialize Azure AI clients
text_analytics_client = TextAnalyticsClient(
    endpoint=azure_ai_endpoint,
    credential=AzureKeyCredential(azure_ai_key)
)

form_recognizer_client = DocumentAnalysisClient(
    endpoint=form_recognizer_endpoint,
    credential=AzureKeyCredential(form_recognizer_key)
)

# Initialize Blob Service client
blob_service_client = BlobServiceClient.from_connection_string(blob_connection_string)

def redact_pii(text):
    chunks = [text[i:i + 5000] for i in range(0, len(text), 5000)]
    redacted_text = ""
    for chunk in chunks:
        response = text_analytics_client.recognize_pii_entities([chunk])
        for document in response:
            chunk_redacted = chunk
            for entity in document.entities:
                chunk_redacted = chunk_redacted.replace(entity.text, '[REDACTED]')
            redacted_text += chunk_redacted
    return redacted_text

def extract_text_from_file(file_path):
    with open(file_path, "rb") as f:
        poller = form_recognizer_client.begin_analyze_document("prebuilt-read", document=f)
    result = poller.result()
    text = ""
    for page in result.pages:
        for line in page.lines:
            text += line.content + "\n"
    return text

def redact_pdf(file_path, redacted_text):
    doc = fitz.open(file_path)
    for page in doc:
        text_instances = page.search_for(redacted_text)
        for inst in text_instances:
            page.add_redact_annot(inst, fill=(0, 0, 0))
        page.apply_redactions()
    redacted_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'redacted_' + os.path.basename(file_path))
    doc.save(redacted_file_path)
    return redacted_file_path

def save_redacted_file(file_path, redacted_text, original_filename):
    if original_filename.lower().endswith('.pdf'):
        return redact_pdf(file_path, redacted_text)
    elif original_filename.lower().endswith(('.png', '.jpg', '.jpeg')):
        image = Image.open(file_path)
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        draw.text((10, 10), redacted_text, fill=(0, 0, 0), font=font)
        redacted_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'redacted_' + original_filename)
        image.save(redacted_file_path)
    else:
        redacted_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'redacted_' + original_filename)
        with open(redacted_file_path, 'w') as f:
            f.write(redacted_text)
    return redacted_file_path

@app.route('/')
def upload_form():
    return '''
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>File Upload</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background-color: #f4f4f4;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }
            .container {
                background-color: #fff;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
                text-align: center;
            }
            h1 {
                margin-bottom: 20px;
            }
            input[type="file"] {
                margin-bottom: 20px;
            }
            input[type="submit"] {
                background-color: #007BFF;
                color: #fff;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                cursor: pointer;
                font-size: 16px;
            }
            input[type="submit"]:hover {
                background-color: #0056b3;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Upload a File</h1>
            <form method="post" enctype="multipart/form-data" action="/upload">
                <input type="file" name="file" required>
                <br>
                <input type="submit" value="Upload">
            </form>
        </div>
    </body>
    </html>
    '''

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(request.url)
    file = request.files['file']
    if file.filename == '':
        return redirect(request.url)
    if file:
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        text = extract_text_from_file(file_path)
        print("Extracted Text:", text)  # Debugging: Print extracted text

        redacted_text = redact_pii(text)
        print("Redacted Text:", redacted_text)  # Debugging: Print redacted text

        redacted_file_path = save_redacted_file(file_path, redacted_text, filename)

        blob_client = blob_service_client.get_blob_client(container=blob_container_name, blob='redacted_' + filename)
        with open(redacted_file_path, 'rb') as data:
            blob_client.upload_blob(data)

        return 'File uploaded and redacted successfully!'

if __name__ == '__main__':
    app.run(debug=True)
