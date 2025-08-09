import azure.functions as func
import datetime
import json
import logging

app = func.FunctionApp()

@app.route(
    route="http_trigger",
    auth_level=func.AuthLevel.ANONYMOUS
)

@app.queue_output(
    arg_name="outputQueue",
    queue_name="http-output-queue",
    connection="AzureWebJobsStorage"
)
def http_trigger(req: func.HttpRequest, outputQueue: func.Out[str]) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    name = req.params.get('name')
    if not name:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            name = req_body.get('name')

    response_message = ""
    if name:
        response_message = f"Hello, {name}. This HTTP triggered function executed successfully."
        
        # --- ADDED: Send a message to the output queue ---
        queue_message = f"HTTP Trigger processed request for: {name} at {datetime.datetime.now().isoformat()}"
        outputQueue.set(queue_message)
        logging.info(f"Sent message to 'http-output-queue': {queue_message}")
        # --- END ADDED ---

        return func.HttpResponse(response_message)
    else:
        response_message = "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response."
        
        # --- ADDED: Send a message to the output queue even without a name ---
        queue_message_no_name = f"HTTP Trigger called without a name at {datetime.datetime.now().isoformat()}"
        outputQueue.set(queue_message_no_name)
        logging.info(f"Sent message to 'http-output-queue': {queue_message_no_name}")
        # --- END ADDED ---
        
        return func.HttpResponse(
            response_message,
            status_code=200
        )


@app.queue_trigger(
    arg_name="azqueue",
    queue_name="http-output-queue",
    connection="AzureWebJobsStorage"
) 
def queue_http_trigger(azqueue: func.QueueMessage):
    logging.warning(
        'Python Queue trigger processed a message: %s',
        azqueue.get_body().decode('utf-8')
    )
