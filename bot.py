import discord
from discord.ext import commands
from groq import Groq
import os
from dotenv import load_dotenv
import asyncio
from datetime import datetime, timedelta
import json

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

# PRIORITY USERS (YOU) - Add your Discord user ID here
# To find your ID: Enable Developer Mode in Discord > Right click your name > Copy ID
PRIORITY_USERS = [
    513520201682386956,  # Elyse's user ID
]

# Track when keys get rate limited (global API limit)
rate_limit_tracker = {}  # {api_key: datetime of rate limit}

# Daily usage tracking
daily_usage = {}  # {user_id: {'date': 'YYYY-MM-DD', 'count': X}}
DAILY_LIMIT = 50  # 50 messages per person per day (doesn't apply to priority users)

# Message queue for when API is busy
message_queue = []
queue_processing = False

def check_daily_limit(user_id):
    """Check if user has hit their daily limit (priority users bypass this)"""
    # Priority users have unlimited messages
    if user_id in PRIORITY_USERS:
        return True, 999999
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    if user_id not in daily_usage:
        daily_usage[user_id] = {'date': today, 'count': 1}
        return True, DAILY_LIMIT - 1
    
    user_data = daily_usage[user_id]
    
    # Reset if new day
    if user_data['date'] != today:
        daily_usage[user_id] = {'date': today, 'count': 1}
        return True, DAILY_LIMIT - 1
    
    # Check limit
    if user_data['count'] >= DAILY_LIMIT:
        return False, 0
    
    user_data['count'] += 1
    remaining = DAILY_LIMIT - user_data['count']
    return True, remaining

# Function to try keys until one works
def get_groq_response(messages, fast_mode=False):
    """
    Get response from Groq API
    fast_mode=True uses smaller/faster model for background tasks like memory extraction
    """
    model = "llama-3.1-8b-instant" if fast_mode else "llama-3.3-70b-versatile"
    max_tokens = 200 if fast_mode else 400
    
    for api_key in API_KEYS:
        # Skip keys that are currently rate limited
        if api_key in rate_limit_tracker:
            if datetime.now() - rate_limit_tracker[api_key] < timedelta(minutes=1):
                continue
            else:
                del rate_limit_tracker[api_key]
        
        try:
            client = Groq(api_key=api_key)
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.8,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            if "rate_limit" in str(e).lower():
                rate_limit_tracker[api_key] = datetime.now()
                print(f"Key rate limited at {datetime.now()}")
                continue
            else:
                raise e
    
    # If all keys failed
    if rate_limit_tracker:
        earliest_available = min(rate_limit_tracker.values()) + timedelta(minutes=1)
        time_until_available = earliest_available - datetime.now()
        
        if time_until_available.total_seconds() > 0:
            minutes = int(time_until_available.total_seconds() // 60)
            seconds = int(time_until_available.total_seconds() % 60)
            
            if minutes > 0:
                return f"um... sorry to break the immersion but you've reached the message limit 😭\nim broke i cant afford unlimited msgs D:\ntry again in like {minutes} min {seconds} sec, maybe?"
            else:
                return f"um... sorry to break the immersion but you've reached the message limit 😭\nim broke i cant afford unlimited msgs D:\ntry again in like {seconds} seconds, maybe?"
        else:
            return "um... sorry to break the immersion but you've reached the message limit 😭\nim broke i cant afford unlimited msgs D:\ntry again soon?"
    
    return "um... sorry to break the immersion but you've reached the message limit 😭\nim broke i cant afford unlimited msgs D:\ntry again tmrw 😭"

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

# Conversation tracking
channel_conversations = {}
active_channels = {}
INACTIVITY_TIMEOUT = 300

# Memory system
bot_memory = {}
memory_queue = []

# File operations
def save_conversations():
    data = {
        'channel_conversations': {str(k): v for k, v in channel_conversations.items()},
        'active_channels': {str(k): v.isoformat() for k, v in active_channels.items()}
    }
    with open('conversations.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def load_conversations():
    try:
        with open('conversations.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            return (
                {int(k): v for k, v in data.get('channel_conversations', {}).items()},
                {int(k): datetime.fromisoformat(v) for k, v in data.get('active_channels', {}).items()}
            )
    except FileNotFoundError:
        return {}, {}

def save_memory():
    with open('bot_memory.json', 'w', encoding='utf-8') as f:
        json.dump(bot_memory, f, indent=2)

def load_memory():
    try:
        with open('bot_memory.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_daily_usage():
    with open('daily_usage.json', 'w', encoding='utf-8') as f:
        json.dump(daily_usage, f, indent=2)

def load_daily_usage():
    try:
        with open('daily_usage.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

channel_conversations, active_channels = load_conversations()
bot_memory = load_memory()
daily_usage = load_daily_usage()

def extract_facts_from_conversation(channel_id):
    if channel_id not in channel_conversations:
        return []
    
    recent = channel_conversations[channel_id][-10:]
    
    fact_extraction_prompt = """Based on this conversation, extract any important facts, preferences, or information about the users that I should remember for future conversations. 

Format as a simple list, one fact per line. Only include genuinely useful information like:
- User preferences (favorite things, dislikes)
- Personal information they shared (job, hobbies, location)
- Important context about their situation
- Recurring topics or interests

Keep it concise. Maximum 5 facts.

Conversation:
""" + "\n".join([msg['content'] for msg in recent])
    
    try:
        facts = get_groq_response([
            {'role': 'system', 'content': 'You are a helpful assistant that extracts key facts from conversations. Be concise.'},
            {'role': 'user', 'content': fact_extraction_prompt}
        ], fast_mode=True)
        
        return [f.strip() for f in facts.split('\n') if f.strip() and not f.strip().startswith('-')][:5]
    except Exception as e:
        print(f"Fact extraction error: {e}")
        return []

async def process_memory_queue():
    print("Memory processor started!")
    while True:
        if memory_queue:
            channel_id = memory_queue.pop(0)
            await asyncio.sleep(2)
            
            try:
                print(f"Extracting facts for channel {channel_id}...")
                new_facts = extract_facts_from_conversation(channel_id)
                
                if new_facts:
                    if str(channel_id) not in bot_memory:
                        bot_memory[str(channel_id)] = {'facts': [], 'last_updated': str(datetime.now())}
                    
                    bot_memory[str(channel_id)]['facts'].extend(new_facts)
                    bot_memory[str(channel_id)]['facts'] = list(set(bot_memory[str(channel_id)]['facts']))[-20:]
                    bot_memory[str(channel_id)]['last_updated'] = str(datetime.now())
                    save_memory()
                    print(f"✓ Updated memory for channel {channel_id} with {len(new_facts)} new facts")
            except Exception as e:
                print(f"Memory extraction error for channel {channel_id}: {e}")
        
        await asyncio.sleep(5)

async def cleanup_inactive_channels():
    while True:
        await asyncio.sleep(60)
        now = datetime.now()
        inactive_channels = []
        
        for channel_id, last_activity in active_channels.items():
            if now - last_activity > timedelta(seconds=INACTIVITY_TIMEOUT):
                inactive_channels.append(channel_id)
        
        for channel_id in inactive_channels:
            del active_channels[channel_id]
            print(f"Channel {channel_id} went inactive")

async def process_message_queue():
    """Process queued messages one at a time to avoid rate limits"""
    global queue_processing
    queue_processing = True
    
    while message_queue:
        queued_item = message_queue.pop(0)
        message = queued_item['message']
        user_message = queued_item['user_message']
        user_id = queued_item['user_id']
        username = queued_item['username']
        channel_id = queued_item['channel_id']
        
        # Process the message
        async with message.channel.typing():
            try:
                messages_to_send = [{'role': 'system', 'content': PERSONALITY}]
                
                if str(channel_id) in bot_memory and bot_memory[str(channel_id)].get('facts'):
                    memory_context = "\n\nThings I remember from our past conversations:\n" + "\n".join(f"- {fact}" for fact in bot_memory[str(channel_id)]['facts'])
                    messages_to_send[0]['content'] += memory_context
                
                if channel_id not in channel_conversations:
                    channel_conversations[channel_id] = []
                
                channel_conversations[channel_id].append({
                    'role': 'user',
                    'content': f'{username}: {user_message}'
                })
                
                if len(channel_conversations[channel_id]) > 20:
                    channel_conversations[channel_id] = channel_conversations[channel_id][-20:]
                
                messages_to_send.extend(channel_conversations[channel_id])
                
                bot_response = get_groq_response(messages_to_send)
                
                channel_conversations[channel_id].append({
                    'role': 'assistant',
                    'content': bot_response
                })
                
            except Exception as e:
                bot_response = f"oop something broke: {e}"
        
        await send_message_naturally(message.channel, bot_response)
        save_conversations()
        
        # Wait between processing messages to avoid rate limits
        await asyncio.sleep(2)
    
    queue_processing = False

@bot.event
async def on_ready():
    print(f'{bot.user} is now running!')
    print(f'Loaded {len(bot_memory)} channel memories')
    print(f'Priority users: {PRIORITY_USERS}')
    bot.loop.create_task(cleanup_inactive_channels())
    bot.loop.create_task(process_memory_queue())

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = bot.user in message.mentions
    channel_id = message.channel.id
    is_active_channel = channel_id in active_channels
    
    if is_dm or is_mentioned or is_active_channel:
        user_id = message.author.id
        is_priority = user_id in PRIORITY_USERS
        
        # Check daily limit (priority users bypass this)
        if not is_priority:
            allowed, remaining = check_daily_limit(user_id)
            
            if not allowed:
                await message.channel.send(
                    "yo you've hit your daily message limit (50 messages/day)\n"
                    "talk to you tomorrow! 💤"
                )
                return
            
            # Warn when close to limit
            if remaining == 5:
                await message.channel.send("btw you got 5 messages left today")
            elif remaining == 1:
                await message.channel.send("heads up this is your last message for today")
        
        user_message = message.content.replace(f'<@{bot.user.id}>','').replace(f'<@!{bot.user.id}>', '').strip()
        
        if not user_message:
            return
        
        # If API is struggling AND user is not priority, queue them
        if len(rate_limit_tracker) >= 2 and not is_priority:
            # Add to queue
            queue_position = len(message_queue) + 1
            message_queue.append({
                'message': message,
                'user_message': user_message,
                'user_id': user_id,
                'username': message.author.display_name,
                'channel_id': channel_id
            })
            
            await message.channel.send(f"yo there's a lot of people talking to me rn lol\nyou're #{queue_position} in line, gimme a sec")
            
            # Start processing queue if not already running
            if not queue_processing:
                bot.loop.create_task(process_message_queue())
            
            return
        
        # Normal processing (for priority users OR when API is healthy)
        active_channels[channel_id] = datetime.now()
        
        if channel_id not in channel_conversations:
            channel_conversations[channel_id] = []
        
        username = message.author.display_name
        channel_conversations[channel_id].append({
            'role': 'user',
            'content': f'{username}: {user_message}'
        })
        
        if len(channel_conversations[channel_id]) > 20:
            channel_conversations[channel_id] = channel_conversations[channel_id][-20:]
        
        if len(channel_conversations[channel_id]) % 15 == 0:
            if channel_id not in memory_queue:
                memory_queue.append(channel_id)
        
        async with message.channel.typing():
            try:
                messages_to_send = [{'role': 'system', 'content': PERSONALITY}]
                
                if str(channel_id) in bot_memory and bot_memory[str(channel_id)].get('facts'):
                    memory_context = "\n\nThings I remember from our past conversations:\n" + "\n".join(f"- {fact}" for fact in bot_memory[str(channel_id)]['facts'])
                    messages_to_send[0]['content'] += memory_context
                
                messages_to_send.extend(channel_conversations[channel_id])
                
                bot_response = get_groq_response(messages_to_send)
                
                channel_conversations[channel_id].append({
                    'role': 'assistant',
                    'content': bot_response
                })
                
            except Exception as e:
                bot_response = f"oop something broke: {e}"
        
        await send_message_naturally(message.channel, bot_response)
        save_conversations()
        save_daily_usage()

async def send_message_naturally(channel, text):
    import re
    import random
    
    if '\n' in text:
        parts = [p.strip() for p in text.split('\n') if p.strip()]
    else:
        parts = re.split(r'(?<=[.!?])\s+', text)
        parts = [s.strip() for s in parts if s.strip()]
    
    if len(parts) == 1:
        text_lower = text.lower()
        break_words = [' lol ', ' lmao ', ' but ', ' and ', ' so ', ' btw ', ' like ']
        for word in break_words:
            if word in text_lower:
                idx = text_lower.index(word)
                parts = [text[:idx+len(word)].strip(), text[idx+len(word):].strip()]
                break
    
    if len(parts) == 1 and len(text) > 100:
        mid = len(text) // 2
        space_idx = text.find(' ', mid)
        if space_idx != -1:
            parts = [text[:space_idx].strip(), text[space_idx:].strip()]
    
    if len(parts) == 1:
        await channel.send(text)
        return
    
    bubbles = []
    i = 0
    while i < len(parts):
        bubble_size = random.choice([1, 1, 2])
        bubble = ' '.join(parts[i:i+bubble_size])
        bubbles.append(bubble)
        i += bubble_size
    
    for i, bubble in enumerate(bubbles):
        if len(bubble) > 2000:
            chunks = [bubble[j:j+2000] for j in range(0, len(bubble), 2000)]
            for chunk in chunks:
                await channel.send(chunk)
                await asyncio.sleep(0.3)
        else:
            await channel.send(bubble)
        
        if i < len(bubbles) - 1:
            async with channel.typing():
                delay = random.uniform(0.8, 2.0)
                await asyncio.sleep(delay)

bot.run(os.getenv('DISCORD_BOT_TOKEN'))