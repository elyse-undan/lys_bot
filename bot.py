import discord
from discord.ext import commands
from groq import Groq
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Load API keys from .env
groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))

# Load personality from file
with open('personality.txt', 'r', encoding='utf-8') as f:
    PERSONALITY = f.read()

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
    
    if isinstance(message.channel, discord.DMChannel) or bot.user in message.mentions:
        user_message = message.content.replace(f'<@{bot.user.id}>', '').strip()
        
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
                response = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {'role': 'system', 'content': PERSONALITY},
                        *conversation_history[user_id]
                    ],
                    temperature=0.8,
                    max_tokens=400
                )
                
                bot_response = response.choices[0].message.content
                
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