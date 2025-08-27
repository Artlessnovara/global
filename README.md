# GLOOBA - Social Media Web Application

Welcome to GLOOBA, a full-featured social media web application built with Python, Flask, and SQLite. This project is designed to simulate a modern social platform with a rich user experience, dynamic content, and real-time interaction features.

## About The Project

GLOOBA is an ambitious project to build a social network from the ground up. It follows an iterative development process, with features being added incrementally. The goal is to create a robust, scalable, and feature-rich platform that showcases best practices in web development with Flask and related technologies.

## Key Features

The application currently includes the following features:

*   **User Authentication:** A complete, multi-step user signup wizard and a secure login/logout system.
*   **Home Feed:** A central feed that displays posts from all users in reverse chronological order.
*   **Post Creation:** Users can create new text-based posts and assign them to a specific "Mode".
*   **Dynamic "Modes" System:** A unique feature where content is categorized into user-selectable "Modes" (e.g., Music, Sports, Education).
*   **User Profiles:** Rich user profile pages with cover photos, avatars, user stats (posts, followers, following), and a grid/list view of their posts.
*   **Follow System:** Users can follow and unfollow each other.
*   **Suggestions:** A `/suggestions` page that recommends users to follow based on their preferred modes.
*   **Real-Time Chat:** A fully functional, real-time 1-on-1 chat system built with Flask-SocketIO.
    *   **Chat Inbox:** Displays recent chats and pending message requests.
    *   **Message Requests:** A system to accept, delete, or block messages from users you don't follow.
    *   **Unread Message Notifications:** A global notification system for unread messages.
*   **Story System:** A complete story feature allowing users to post ephemeral image-based stories that last for 24 hours.
    *   Custom UI for creating stories vs. viewing stories from others.
    *   Full-screen story viewer.
*   **Reels Page:** A full-screen, vertical-scrolling interface for video content.
*   **Comprehensive Test Suite:** The project is backed by a suite of `pytest` tests to ensure reliability and catch regressions.

## Getting Started

To get a local copy up and running, follow these simple steps.

### Prerequisites

*   Python 3.8+
*   pip

### Installation

1.  **Clone the repo**
    ```sh
    git clone https://github.com/your_username/glooba.git
    cd glooba
    ```

2.  **Create a virtual environment**
    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  **Install dependencies**
    ```sh
    pip install -r requirements.txt
    ```

4.  **Initialize the Database**
    The first time you run the app, you need to initialize the SQLite database and seed it with the available "Modes".
    ```sh
    flask init-db
    ```

5.  **Run the Application**
    ```sh
    flask run
    ```
    The application will be available at `http://127.0.0.1:5000`.

## License

Distributed under the MIT License. See `LICENSE.txt` for more information.
