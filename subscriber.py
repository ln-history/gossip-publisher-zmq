import zmq

# ZeroMQ Context
context = zmq.Context()

# Define the socket type
socket = context.socket(zmq.SUB)

# Connect to the publisher
socket.connect("tcp://127.0.0.1:5675")

# Subscribe to all topics
socket.setsockopt_string(zmq.SUBSCRIBE, "")

count = 0

# Open a test file to write the received messages
with open("output.txt", "w") as output_file:
    print("Subscriber started, waiting for messages...")

    try:
        while True:
            # Receive topic and message
            topic = socket.recv_string()
            message = socket.recv_json()

            count += 1

            # Print the message
            print(f"Message count: {count}")
            print(f"Topic: {topic}")
            print(f"Metadata: {message['metadata']}")
            print(f"Raw data: {message['raw_hex']}")
            print(f"Parsed: {message['parsed']}")
            print("-" * 80)

            # Write to the file
            output_file.write(f"Message count: {count}\n")
            output_file.write(f"Topic: {topic}\n")
            output_file.write(f"Metadata: {message['metadata']}")
            output_file.write(f"Raw data: {message['raw_hex']}")
            output_file.write(f"Parsed: {message['parsed']}")
            output_file.write("-" * 80 + "\n")

    except KeyboardInterrupt:
        print("Subscriber closing...")
    finally:
        socket.close()
        context.term()
