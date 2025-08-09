# http-trigger-azure-function
Create Azure Function
1. Install azure function cli
2. Create project folder
3. Initialize azure function using func init <project folder name> --worker-runtime python --model V2
4. Change directory to <project folder name>
5. Add new azure function app from template using func new --template "Http Trigger" --name <http trigger app name>
6. Add new azure function app for queue storage trigger from template using func new --template "Queue Trigger" --name <queue http trigger app name>, fill queuename and QueueConnectionString

