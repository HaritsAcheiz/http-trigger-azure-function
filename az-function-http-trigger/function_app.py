import azure.functions as func
import datetime
import json
import logging
from openai import AzureOpenAI
from msal import ConfidentialClientApplication
import requests
import os

app = func.FunctionApp()

# 1. HTTP route: send request data to queue
@app.route(route="generate-email", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@app.queue_output(arg_name="generateEmailQueue", queue_name="generate-email-queue", connection="AzureWebJobsStorage")
def generate_email(req: func.HttpRequest, generateEmailQueue: func.Out[str]) -> func.HttpResponse:
    try:
        req_body = req.get_json()
    except Exception as e:
        logging.error(f"Error parsing request body: {e}")
        return func.HttpResponse("Invalid JSON body.", status_code=400)

    # Validate required fields
    required_fields = ['subject', 'body', 'sender_email']
    if not all(field in req_body for field in required_fields):
        return func.HttpResponse(
            "Please provide 'subject', 'body', and 'sender_email' in the request body.",
            status_code=400
        )

    # Send the request data to the queue as JSON
    generateEmailQueue.set(json.dumps(req_body))
    logging.info("Request data sent to generate-email-queue.")

    return func.HttpResponse(
        "Your request has been queued for processing.",
        status_code=202
    )

# 2. Queue trigger: process messages and generate reply
@app.queue_trigger(arg_name="msg", queue_name="generate-email-queue", connection="AzureWebJobsStorage")
@app.queue_output(arg_name="outlookDraftQueue", queue_name="outlook-draft-queue", connection="AzureWebJobsStorage")
def process_generate_email(msg: func.QueueMessage, outlookDraftQueue: func.Out[str]) -> None:
    logging.info("Processing message from generate-email-queue.")
    try:
        req_body = json.loads(msg.get_body().decode('utf-8'))
    except Exception as e:
        logging.error(f"Error decoding queue message: {e}")
        return

    # Extract fields
    original_email_subject = req_body.get('subject')
    original_email_body = req_body.get('body')
    sender_email = req_body.get('sender_email')
    recipient_email = req_body.get('recipient_email')
    recipient_name = req_body.get('recipient_name')

    # Initialize OpenAI client
    try:
        api_key = os.environ["AZURE_OPENAI_API_KEY"]
        azure_endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        deployment_name = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]
        openai_client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version="2024-02-01"
        )
    except Exception as e:
        logging.error(f"Error initializing Azure OpenAI client: {e}")
        return

    # Prepare prompt
    system_role = "system"
    system_content = "You are a helpful assistant that drafts professional email replies. Be concise and polite."
    user_role = "user"
    user_content = f"The following is an email from '{sender_email}' with the subject '{original_email_subject}' and body:\n\n---\n'{original_email_body}'\n---\n\nDraft a concise and polite reply."
    if recipient_name:
        user_content += f"\n\nSign off as {recipient_name} with position as Magiccars Customer Care and email contact {recipient_email}."

    prompt_messages = [
        {"role": system_role, "content": system_content},
        {"role": user_role, "content": user_content}
    ]

    # Generate reply
    try:
        response = openai_client.chat.completions.create(
            model=deployment_name,
            messages=prompt_messages,
            temperature=0.7,
            max_tokens=250,
            top_p=0.95,
            frequency_penalty=0,
            presence_penalty=0,
            stop=None
        )
        
        reply_content = response.choices[0].message.content.strip()
        reply_subject = f"Re: {original_email_subject}"
        logging.info(f"Reply generated: {reply_subject} - {reply_content[:100]}...")

        # Store as draft in Outlook
        draft_payload = {
            "subject": reply_subject,
            "body": reply_content,
            "recipient_email": sender_email,
            "sender_email": recipient_email
        }

        outlookDraftQueue.set(json.dumps(draft_payload))
        logging.info("Reply sent to outlook-draft-queue.")

        airtable_api_key = os.environ["AIRTABLE_API_KEY"]
        airtable_url_metadata = os.environ["AIRTABLE_URL_METADATA"]
        airtable_url_training = os.environ["AIRTABLE_URL_TRAINING"]
        headers = {
            "Authorization": f"Bearer {airtable_api_key}",
            "Content-Type": "application/json"
        }

         # Email metadata record
        metadata_record = {
            "fields": {
                "original_email_subject": original_email_subject,
                "original_email_body": original_email_body,
                "sender_email": sender_email,
                "recipient_email": recipient_email,
                "recipient_name": recipient_name
            }
        }
        
        requests.post(airtable_url_metadata, headers=headers, json=metadata_record)
        
        # Dataset training record
        training_record = {
            "fields": {
                "system_role": system_role,
                "system_content": system_content,
                "user_role": user_role,
                "user_content": user_content,
                "reply_draft": reply_content,
                "reply_sent": "",
                "status": "Draft"
            }
        }
        
        requests.post(airtable_url_training, headers=headers, json=training_record)
        
    except Exception as e:
        logging.error(f"Error during OpenAI API call or reply generation: {e}")

# 3. Queue trigger: process create draft email in outlook
@app.route(route="create-outlook-draft", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def create_outlook_draft(req: func.HttpRequest) -> func.HttpResponse:
    req_body = req.get_json()

    # Get credentials from environment variables
    tenant_id = os.environ["AZURE_TENANT_ID"]
    client_id = os.environ["AZURE_CLIENT_ID"]
    client_secret = os.environ["AZURE_CLIENT_SECRET"]

    # Authenticate with Microsoft Graph
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret
    )
    scopes = ["https://graph.microsoft.com/.default"]
    result = app.acquire_token_for_client(scopes=scopes)
    access_token = result.get("access_token")

    if not access_token:
        logging.error("Could not obtain access token for Microsoft Graph.")
        return

    # Create draft email payload
    draft_payload = {
        "message": {
            "subject": req_body["subject"],
            "body": {
                "contentType": "Text",
                "content": req_body["body"]
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": req_body["recipient_email"]
                    }
                }
            ],
            "from": {
                "emailAddress": {
                    "address": req_body["sender_email"]
                }
            }
        },
        "saveToSentItems": "false"
    }

    # Send request to create draft
    url = f"https://graph.microsoft.com/v1.0/users/{req_body["sender_email"]}/mailFolders/drafts/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    response = requests.post(url, headers=headers, json=draft_payload)
    if response.status_code == 201:
        logging.info("Draft email created successfully in Outlook.")
        return func.HttpResponse("Draft created.", status_code=201)
    else:
        logging.error(f"Failed to create draft email: {response.text}")
        return func.HttpResponse("Failed to create draft.", status_code=response.status_code)
    