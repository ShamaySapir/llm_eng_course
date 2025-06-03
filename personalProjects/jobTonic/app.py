from flask import Flask, request, jsonify, make_response
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time
import os
from dotenv import load_dotenv
from openai import AzureOpenAI
import uuid


load_dotenv()  # Load environment variables from .env file

# Set up your client with environment variables
api_key = os.getenv('AZURE_OPENAI_API_KEY')
endpoint = os.getenv('ENDPOINT')
version = os.getenv('VERSION')
deployment = os.getenv('DEPLOYMENT_4_1nano')

client = AzureOpenAI(
    azure_endpoint=endpoint, 
    api_key=api_key,
    api_version=version
)


# A class to represent a Webpage

# Some websites need you to use proper headers when fetching them:
headers = {
 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
}

class Website:
    """
    A utility class to represent a Website that we have scraped, now with Selenium for dynamic websites.
    """

    def __init__(self, url):
        self.url = url

        # Set up Selenium WebDriver with Chrome
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')  # Run in headless mode
        options.add_argument('--disable-gpu')
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

        # Load the webpage
        driver.get(url)
        time.sleep(5)  # Wait for the page to load completely

        # Get the page source and parse it with BeautifulSoup
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        driver.quit()  # Close the browser

        self.title = soup.title.string if soup.title else "No title found"
        if soup.body:
            for irrelevant in soup.body(["script", "style", "img", "input"]):
                irrelevant.decompose()
            self.text = soup.body.get_text(separator="\n", strip=True)
        else:
            self.text = ""

    def get_contents(self):
        return f"Webpage Title:\n{self.title}\nWebpage Contents:\n{self.text}\n\n"


def read_website(url):
    try:
        website = Website(url)
        return website.text
    except Exception as e:
        return f"Error reading website: {e}"
    
def read_text_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            text = file.read()
        return text
    except Exception as e:
        return f"Error reading text file: {e}"

# The system prompt for job postings
job_posting_system_prompt = read_text_file("job_posting_system_prompt.txt")

read_website_function = {
    "name": "read_website",
    "description": "Get the content of the website by its link. Call this whenever you need to read link content, for example when a customer provides a link to a job posting.",
    "parameters": {
        "type": "object",
        "properties": {
            "link": {
                "type": "string",
                "description": "The link to the website you want to read. For example: https://www.example.com/job/software-engineer",
            },
        },
        "required": ["link"],
        "additionalProperties": False
    }
}

def call_tool(reply, messages): 
    tool_responses = []
    messages.append(reply)

    for tool_call in reply.tool_calls:
        if tool_call.function.name == "read_website":
            try:
                arguments = json.loads(tool_call.function.arguments)
                link = arguments.get('link')
                print(link)
                # Validate the link
                if not link or not link.startswith("http"):
                    raise ValueError(f"Invalid link: {link}")
                
                website_text = read_website(link)
                tool_responses.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": website_text
                })
            except Exception as e:
                # Handle errors gracefully
                error_message = f"Error processing tool_call_id {tool_call.id}: {e}"
                tool_responses.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": error_message
                })

        else:
            error_message = f"Error processing tool_call_id {tool_call.id}: Unsupported function {tool_call.function.name}"
            tool_responses.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": error_message
            })

    messages.extend(tool_responses)
    followup = client.chat.completions.create(
        model=deployment,
        messages=messages
    )

    return followup.choices[0].message.content

app = Flask(__name__)

# Your existing chat function (with any imports it needs)
def chat(message, history):
    messages = [{"role": "system", "content": job_posting_system_prompt}] + history + [{"role": "user", "content": message}]
    print(messages)
    response = client.chat.completions.create(model=deployment, 
                                              messages=messages, tools = [{"type": "function", "function": read_website_function}])
    print(response)
    if response.choices[0].finish_reason=="tool_calls":
        message = response.choices[0].message
        response = call_tool(message, messages)
        response = client.chat.completions.create(model=deployment, messages=messages)
    
    return response.choices[0].message.content

# Create a web endpoint
@app.route('/chat', methods=['POST'])
def chat_endpoint():
    try:
        data = request.json
        message = data.get('message', '')
        history = data.get('history', [])

        session_id = request.cookies.get('session_id')
        if not session_id:
            session_id = str(uuid.uuid4())  # Generate a new session ID
            response = make_response(jsonify({
                'message': 'New session started',
                'session_id': session_id,
                'status': 'success'
            }))
            # שמור את ה-session_id בעוגיה
            response.set_cookie('session_id', session_id)
        
        response = chat(message, history)
        
        return jsonify({
            'response': response,
            'status': 'success'
        })
    except Exception as e:
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

# Health check endpoint
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)