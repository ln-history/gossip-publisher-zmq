import zmq
from collections import defaultdict

# ZeroMQ Context
context = zmq.Context()

# Define the socket type
socket = context.socket(zmq.SUB)

# Connect to the publisher
socket.connect("tcp://127.0.0.1:5675")

# Subscribe to all topics
socket.setsockopt_string(zmq.SUBSCRIBE, "")

count = 0
msg_counts = defaultdict(int)

print("Subscriber started, waiting for messages...")

try:
    while True:
        # Receive multipart message (topic + payload)
        msg = socket.recv_multipart()
        print("Received:", msg)

        # msg_counts[topic] += 1
        count += 1


        if count % 1_000 == 0:
            print(f"Consumed {count} messages so far...")

except KeyboardInterrupt:
    print("\nSubscriber closing...")

finally:
    socket.close()
    context.term()

# Print summary stats
print("\n=== Gossip Stats ===")
print(f"Total messages: {count}")
for topic, cnt in msg_counts.items():
    print(f"Topic '{topic}': {cnt} messages ({cnt/count:.2%})")
