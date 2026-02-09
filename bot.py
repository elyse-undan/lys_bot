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

rate_limit_tracker = {}  # {api_key: datetime of rate limit}

# Function to try keys until one works
def get_groq_response(messages, fast_mode=False):
    """
    Get response from Groq API
    fast_mode=True uses smaller/faster model for background tasks like memory extraction
    """
    model = "llama-3.1-8b-instant" if fast_mode else "llama-3.3-70b-versatile"
    max_tokens = 200 if fast_mode else 400
    
    for api_key in API_KEYS:
        # Skip keys that are currently rate limited (if we know about it)
        if api_key in rate_limit_tracker:
            # Groq rate limits reset after 1 minute typically
            if datetime.now() - rate_limit_tracker[api_key] < timedelta(minutes=1):
                continue
            else:
                # It's been over a minute, remove from tracker and try again
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
            # If rate limit error, track it and try next key
            if "rate_limit" in str(e).lower():
                rate_limit_tracker[api_key] = datetime.now()
                print(f"Key rate limited at {datetime.now()}")
                continue
            else:
                # If other error, raise it
                raise e
    
    # If all keys failed, calculate when the earliest one will be available
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
channel_conversations = {}  # {channel_id: [messages with usernames]}
active_channels = {}  # {channel_id: last_activity}
INACTIVITY_TIMEOUT = 300  # 5 minutes in seconds

# Memory system
bot_memory = {}  # {channel_id: {'facts': [], 'last_updated': timestamp}}
memory_queue = []  # Queue of channels that need fact extraction

# File operations for persistence
def save_conversations():
    """Save all conversations to a file"""
    data = {
        'channel_conversations': {str(k): v for k, v in channel_conversations.items()},
        'active_channels': {str(k): v.isoformat() for k, v in active_channels.items()}
    }
    with open('conversations.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def load_conversations():
    """Load conversations from file"""
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
    """Save bot memory to file"""
    with open('bot_memory.json', 'w', encoding='utf-8') as f:
        json.dump(bot_memory, f, indent=2)

def load_memory():
    """Load bot memory from file"""
    try:
        with open('bot_memory.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# Load saved data
channel_conversations, active_channels = load_conversations()
bot_memory = load_memory()

def extract_facts_from_conversation(channel_id):
    """
    Extract important facts from conversation using LLM
    Uses fast_mode for speed (smaller model, fewer tokens)
    """
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
        ], fast_mode=True)  # Use fast model for background task
        
        return [f.strip() for f in facts.split('\n') if f.strip() and not f.strip().startswith('-')][:5]
    except Exception as e:
        print(f"Fact extraction error: {e}")
        return []

# Background task to process memory updates
async def process_memory_queue():
    """
    Process fact extraction in the background without blocking responses
    This runs continuously and processes queued channels
    """
    print("Memory processor started!")
    while True:
        if memory_queue:
            channel_id = memory_queue.pop(0)
            
            # Small delay to not spam API
            await asyncio.sleep(2)
            
            try:
                print(f"Extracting facts for channel {channel_id}...")
                new_facts = extract_facts_from_conversation(channel_id)
                
                if new_facts:
                    if str(channel_id) not in bot_memory:
                        bot_memory[str(channel_id)] = {'facts': [], 'last_updated': str(datetime.now())}
                    
                    # Add new facts and keep only last 20
                    bot_memory[str(channel_id)]['facts'].extend(new_facts)
                    bot_memory[str(channel_id)]['facts'] = list(set(bot_memory[str(channel_id)]['facts']))[-20:]  # Remove duplicates
                    bot_memory[str(channel_id)]['last_updated'] = str(datetime.now())
                    save_memory()
                    print(f"✓ Updated memory for channel {channel_id} with {len(new_facts)} new facts")
            except Exception as e:
                print(f"Memory extraction error for channel {channel_id}: {e}")
        
        await asyncio.sleep(5)  # Check queue every 5 seconds

# Background task to clean up inactive channels
async def cleanup_inactive_channels():
    """Remove inactive channels from tracking to save memory"""
    while True:
        await asyncio.sleep(60)  # Check every minute
        now = datetime.now()
        inactive_channels = []
        
        for channel_id, last_activity in active_channels.items():
            if now - last_activity > timedelta(seconds=INACTIVITY_TIMEOUT):
                inactive_channels.append(channel_id)
        
        for channel_id in inactive_channels:
            del active_channels[channel_id]
            print(f"Channel {channel_id} went inactive")

@bot.event
async def on_ready():
    print(f'{bot.user} is now running!')
    print(f'Loaded {len(bot_memory)} channel memories')
    # Start background tasks
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
        active_channels[channel_id] = datetime.now()
        
        user_message = message.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
        
        if not user_message:
            return
        
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
                print(f"Queued channel {channel_id} for memory extraction")
        
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
        
        # REMOVED THE DUPLICATE SEND - Only use send_message_naturally
        await send_message_naturally(message.channel, bot_response)
        
        save_conversations()

async def send_message_naturally(channel, text):
    """
    Send message like a real person texting - multiple messages with random delays
    Shows typing indicator between messages
    """
    import re
    import random
    
    # First try splitting by newlines (if the bot uses them)
    if '\n' in text:
        parts = [p.strip() for p in text.split('\n') if p.strip()]
    else:
        # Split by sentence-ending punctuation (.!?)
        parts = re.split(r'(?<=[.!?])\s+', text)
        parts = [s.strip() for s in parts if s.strip()]
    
    # If still just one part, try splitting by common breakpoints
    if len(parts) == 1:
        # Try splitting on "lol", "lmao", "but", "and", "so" etc
        text_lower = text.lower()
        
        # Look for natural break points
        break_words = [' lol ', ' lmao ', ' but ', ' and ', ' so ', ' btw ', ' like ']
        for word in break_words:
            if word in text_lower:
                # Split on first occurrence
                idx = text_lower.index(word)
                parts = [text[:idx+len(word)].strip(), text[idx+len(word):].strip()]
                break
    
    # If STILL one part and it's long, split it roughly in half
    if len(parts) == 1 and len(text) > 100:
        mid = len(text) // 2
        # Find nearest space to split at
        space_idx = text.find(' ', mid)
        if space_idx != -1:
            parts = [text[:space_idx].strip(), text[space_idx:].strip()]
    
    # If just 1 part and it's short, send it
    if len(parts) == 1:
        await channel.send(text)
        return
    
    # Group parts into "text bubbles" (1-2 parts per bubble for casual feel)
    bubbles = []
    i = 0
    while i < len(parts):
        bubble_size = random.choice([1, 1, 2])  # mostly 1, sometimes 2
        bubble = ' '.join(parts[i:i+bubble_size])
        bubbles.append(bubble)
        i += bubble_size
    
    # Send each bubble as a separate message with random delays
    for i, bubble in enumerate(bubbles):
        if len(bubble) > 2000:
            chunks = [bubble[j:j+2000] for j in range(0, len(bubble), 2000)]
            for chunk in chunks:
                await channel.send(chunk)
                await asyncio.sleep(0.3)
        else:
            await channel.send(bubble)
        
        # Show typing indicator and delay before next message (except after last one)
        if i < len(bubbles) - 1:
            # Start typing indicator
            async with channel.typing():
                # Random delay while "typing" (between 0.8 and 2.0 seconds)
                delay = random.uniform(0.8, 2.0)
                await asyncio.sleep(delay)

bot.run(os.getenv('DISCORD_BOT_TOKEN'))