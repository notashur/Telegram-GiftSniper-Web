# app.py
from admin_routes import app

# import models
# a = models.UserManager().add_user('ash2', '123', "2025-6-13")
# print(a)
# quit()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5913)
