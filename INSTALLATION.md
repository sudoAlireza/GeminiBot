# How to Use Google Gemini AI in Your Personal Telegram Bot on Your Own Server

## Introduction

Recently, Google rebranded its Generative Language Model from Bard to Gemini and introduced an official SDK for several programming languages to collaborate with the Gemini API. This transformation goes beyond a just name change; it signifies a notable upgrade to the language model. According to benchmarks, Gemini Pro, Google's free version, emerges as a serious rival to OpenAI's ChatGPT, even with better performance in certain aspects.

As an everyday user of Telegram, a versatile and feature-rich messenger, I'm using it for my communication needs. Telegram transcends being a more than just messenger, evolving into a comprehensive platform. If you're reading this story, chances are you're already acquainted with Telegram and its bot functionality.

So I've crafted a Telegram bot using Gemini's official Python SDK to seamlessly integrate Gemini's chat feature into the Telegram environment. To use exclusivity, I've limited access to [GeminiBot](https://t.me/GeminiPersonalBot) to my personal Telegram account. This restriction is due to Gemini Pro's usage limitations, allowing a maximum API call rate of 60 requests per minute. However, for those want to create Telegram bot for public usage, I recommend to acquire Gemini Ultra, enabling the removal of API call limitation.

Throughout this story, I'll try to explain of utilizing GeminiBot's repository, providing insights on how to build and maintain your personalized chatbot.

## Features

* Engage in online conversations with Google's Gemini AI chatbot
* Maintain conversation history for continuing or initiating new discussions
* Send images with captions to receive responses based on the image content. For example, the bot can read text within images and convert it to text.

https://github.com/sudoAlireza/GeminiBot/assets/87416117/beeb0fd2-73c6-4631-baea-2e3e3eeb9319

## Project Structure

```plaintext
This is the main structure of the GeminiBot project:
.
├── bot
│   ├── conversation_handlers.py
│   ├── __init__.py
│   └── __pycache__
├── core.py
├── database
│   ├── database.py
│   ├── __init__.py
│   └── __pycache__
├── Docs.md
├── helpers
│   ├── helpers.py
│   ├── __init__.py
│   ├── inline_paginator.py
│   └── __pycache__
├── __init__.py
├── main.py
├── pickles
│   └── __init__.py
├── README.md
├── requirements.txt
├── .env
└── safety_settings.json
```

For the ease of deployment and usage, I opted for SQLite3 as the database to store records of conversations per user. It stores conversations with the Telegram user account ID, ensuring that users cannot access others' conversations if your bot serves multiple users. To save Gemini conversation objects for loading previous conversations, I utilized Pickles and stored them in the `pickles` folder.

In `core.py`, there is a Python class for communicating with Gemini's Python SDK, which you can easily customize. The `safety_settings.json` file is designed to align with Gemini's [Safety Settings](https://ai.google.dev/docs/safety_setting_gemini) policies, allowing you to restrict each conversation for topics such as hate speech and more.

In the `.env` file, you should set your Telegram Bot token, Gemini API key, and your Telegram account ID. If you need to change user restrictions, refer to the `restricted` decorator in the `bot/conversation_handlers.py` file.

In this story, I won't explain how to create a Telegram bot using [BotFather](https://t.me/BotFather) or how to obtain your API key for Gemini API. As a developer, you are likely familiar with these steps. You can refer to the [Telegram Documentations](https://core.telegram.org/bots/tutorial#obtain-your-bot-token) and [Google's Documents](https://ai.google.dev/tutorials/setup) for guidance on obtaining an API key.

Your `.env` file should resemble the following:

```dotenv
TELEGRAM_BOT_TOKEN=<Your Telegram Bot Token>
GEMINI_API_TOKEN=<Your Gemini API key>
AUTHORIZED_USER=<Your Telegram account ID number>
```

To obtain your Telegram account ID, you can send a message to Show Json Bot in Telegram. It will show your account information in a JSON format, and you can find your account ID in the chat section of the JSON file that the bot responds with. Note that the account ID is different from your username and is not mutable for Telegram accounts unless you delete your account and create another one.

If you want to modify user restrictions, you can examine the `restricted` decorator in the `bot/conversation_handlers.py` file.

## Deploy and Run Telegram Bot on Linux Server

To deploy your bot there are several ways like Heroku and PythonAnywhere or other PaaS providers. I prefer to use bare Linux VPS and supervisor. First of all clone the project in your Linux machine:
```
git clone https://github.com/sudoAlireza/GeminiBot.git
```
Then create `.env` file in root of the project and fill variables with tokens and ID's you got from Google and Telegram. In the next step install project reqirements with this code in your Virual environment:
```
python3 -m venv venv --prompt GeminiBot
source venv/bin/activate
pip install -r requirements.txt
```
And to use Supervisor to run your bot as deamon install it first:
```
sudo apt update
sudo apt install supervisor -y
```

and create a file inside supervisor conf.d with name of project you prefer:
```
touch /etc/supervisor/conf.d/gemini_bot.conf # Instead of gemini_bot you can put your prefered name
vim touch /etc/supervisor/conf.d/gemini_bot.conf # If you don't like vim, you can use nano
```

and config use this template in `gemini_bot.conf`
```
[program:gemini_bot]
command=<PROJECT_DIR>/venv/bin/python3 <PROJECT_DIR>/main.py
directory=<PROJECT_DIR>
restarts=4
autostart=true
autorestart=true
log_stderr=true
log_stdout=true
stderr_logfile=/var/log/supervisor/gemini_bot.err.log
stdout_logfile=/var/log/supervisor/gemini_bot.out.log
```

Then update and run Supervisor

```
sudo systemctl status supervisor
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start gemini_bot
```

And if you didn't miss anything, you can use your bot in Telegram.


## Ideas for Further Developments

* **Removing Specific Conversations from History:** In the first version of this bot, users can see conversations they have saved in history, and by clicking on the conversation code, they can continue from where they left off. In future versions, users will be able to delete conversations one by one or all at once with a single button.

* **Adding Conversation Feature to the Images Section:** In the current version, users can send an image with a caption to the bot and use the `gemini-pro-vision` model to ask or talk about the image. However, they can't keep a conversation like the `gemini-pro` model due to limitations in the current SDK. We can implement custom logic with prompts to address this.

* **Handling Long Responses in Multiple Messages:** Due to Telegram's limitation on sending more than 4096 characters, there are some challenges in responding to long messages. I'll find a solution to handle them in several messages without markdown issues and other related problems.

* **Adding Tests and Facilitating Deployment:** Tests are crucial, and a project without them is essentially worthless. I'll be working on adding tests to ensure the robustness of the code. Additionally, I'll aim to streamline the deployment process for ease of use.

Feel free to share your ideas here or open issues and pull requests in the [GeminiBot](https://github.com/sudoAlireza/GeminiBot) GitHub repository. I've created a To-Do list in the project documentation to keep track of upcoming developments.