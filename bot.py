import discord
from discord.ext import commands
from groq import Groq
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Load API keys from .env
API_KEYS = [
    os.getenv('GROQ_API_KEY_1'),
    os.getenv('GROQ_API_KEY_2'),
    os.getenv('GROQ_API_KEY_3'),
]

# Remove None values
API_KEYS = [k for k in API_KEYS if k]

# Function to try keys until one works
def get_groq_response(messages):
    for api_key in API_KEYS:
        try:
            client = Groq(api_key=api_key)
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.8,
                max_tokens=400
            )
            return response.choices[0].message.content
        except Exception as e:
            # If rate limit error, try next key
            if "rate_limit" in str(e).lower():
                continue
            else:
                # If other error, raise it
                raise e
    
    # If all keys failed
    return "um... sorry.. all the keys are rate limited rn\nim broke i cant afford more D:\ntry again tmrw 😭"

# Load personality from file
try:
    with open('personality.txt', 'r', encoding='utf-8') as f:
        PERSONALITY = f.read()
except FileNotFoundError:
    PERSONALITY = os.getenv('PERSONALITY', 'You are Elyse, a friendly chatbot.')

# Set up Discord bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

conversation_history = {}

@bot.event
async def on_ready():
    print(f'{bot.user} is now running!')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    # Respond to ALL DMs without needing @
    if isinstance(message.channel, discord.DMChannel):
        user_message = message.content.strip()
        
        user_id = message.author.id
        if user_id not in conversation_history:
            conversation_history[user_id] = []
        
        conversation_history[user_id].append({
            'role': 'user',
            'content': user_message
        })
        
        if len(conversation_history[user_id]) > 10:
            conversation_history[user_id] = conversation_history[user_id][-10:]
        
        async with message.channel.typing():
            try:
                bot_response = get_groq_response([
                    {'role': 'system', 'content': PERSONALITY},
                    *conversation_history[user_id]
                ])
                
                conversation_history[user_id].append({
                    'role': 'assistant',
                    'content': bot_response
                })
            except Exception as e:
                bot_response = f"oop something broke: {e}"
        
        if len(bot_response) > 2000:
            for i in range(0, len(bot_response), 2000):
                await message.channel.send(bot_response[i:i+2000])
        else:
            await message.channel.send(bot_response)

bot.run(os.getenv('DISCORD_BOT_TOKEN'))