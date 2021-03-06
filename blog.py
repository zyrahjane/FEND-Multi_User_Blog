import os
import re
import random
import hashlib
import hmac
from string import letters

import webapp2
import jinja2
import blogfunc

from google.appengine.ext import db

template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir),
                               autoescape=True)

secret = 'fart'


# Following is taken from past homework to deal with logins and passwords
def render_str(template, **params):
    t = jinja_env.get_template(template)
    return t.render(params)


def make_secure_val(val):
    return '%s|%s' % (val, hmac.new(secret, val).hexdigest())


def check_secure_val(secure_val):
    val = secure_val.split('|')[0]
    if secure_val == make_secure_val(val):
        return val


class BlogHandler(webapp2.RequestHandler):
    def write(self, *a, **kw):
        self.response.out.write(*a, **kw)

    def render_str(self, template, **params):
        params['user'] = self.user
        return render_str(template, **params)

    def render(self, template, **kw):
        self.write(self.render_str(template, **kw))

    def set_secure_cookie(self, name, val):
        cookie_val = make_secure_val(val)
        self.response.headers.add_header(
            'Set-Cookie',
            '%s=%s; Path=/' % (name, cookie_val))

    def read_secure_cookie(self, name):
        cookie_val = self.request.cookies.get(name)
        return cookie_val and check_secure_val(cookie_val)

    def login(self, user):
        self.set_secure_cookie('user_id', str(user.key().id()))

    def logout(self):
        self.response.headers.add_header('Set-Cookie', 'user_id=; Path=/')

    def initialize(self, *a, **kw):
        webapp2.RequestHandler.initialize(self, *a, **kw)
        uid = self.read_secure_cookie('user_id')
        self.user = uid and User.by_id(int(uid))


def users_key(group='default'):
    return db.Key.from_path('users', group)


class User(db.Model):
    name = db.StringProperty(required=True)
    pw_hash = db.StringProperty(required=True)
    email = db.StringProperty()

    @classmethod
    def by_id(cls, uid):
        return User.get_by_id(uid, parent=users_key())

    @classmethod
    def by_name(cls, name):
        u = User.all().filter('name =', name).get()
        return u

    @classmethod
    def register(cls, name, pw, email=None):
        pw_hash = blogfunc.make_pw_hash(name, pw)
        return User(parent=users_key(),
                    name=name,
                    pw_hash=pw_hash,
                    email=email)

    @classmethod
    def login(cls, name, pw):
        u = cls.by_name(name)
        if u and blogfunc.valid_pw(name, pw, u.pw_hash):
            return u


def blog_key(name='default'):
    return db.Key.from_path('blogs', name)


class Post(db.Model):
    # Post will keep track of title, content and addition the number of likes
    subject = db.StringProperty(required=True)
    content = db.TextProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)
    last_modified = db.DateTimeProperty(auto_now=True)
    author = db.StringProperty(required=True)
    likes = db.IntegerProperty(default=0)

    def render(self):
        self._render_text = self.content.replace('\n', '<br>')
        return render_str("post.html", p=self)


class Comment(db.Model):
    # Comment is like a post but has a parent of a post,
    # will be stored under post_id
    content = db.TextProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)
    last_modified = db.DateTimeProperty(auto_now=True)
    author = db.StringProperty(required=True)
    post_id = db.IntegerProperty(required=True)

    def render(self, post_id):
        self._render_text = self.content.replace('\n', '<br>')
        return render_str("comment.html", c=self, post_id=post_id)


class Like(db.Model):
    # database for the likes will keep track of who liked the post
    user_id = db.StringProperty(required=True)
    post_id = db.IntegerProperty(required=True)

    def render(self, post_id):
        self._render_text = self.content.replace('\n', '<br>')
        return render_str("like.html", l=self, post_id=post_id)


class BlogFront(BlogHandler):
    # Taken from homework set
    def get(self):
        posts = db.GqlQuery(
            "select * from Post order by created desc limit 10"
        )
        comments = db.GqlQuery("select * from Comment order by created desc")
        self.render('front.html', posts=posts, comments=comments)


class PostPage(BlogHandler):
    def get(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)

        if not post:
            self.error(404)
            return
        comments = db.GqlQuery("select * from Comment order by created desc")
        self.render("permalink.html", post=post, comments=comments)


class NewPost(BlogHandler):
    def get(self):
        if self.user:
            self.render("newpost.html")
        else:
            self.redirect("/login")

    def post(self):
        if not self.user:
            return self.redirect('/login')

        subject = self.request.get('subject')
        content = self.request.get('content')

        if subject and content:
            p = Post(parent=blog_key(), subject=subject, content=content,
                     author=self.user.name)
            p.put()
            self.redirect('/%s' % str(p.key().id()))
        else:
            error = "subject and content, please!"
            self.render("newpost.html", subject=subject, content=content,
                        error=error)


class EditPost(BlogHandler):
    def get(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)

        # checks if post exists
        if not post:
            return self.redirect('/')

        if self.user and self.user.name == post.author:
            return self.render('editpost.html', subject=post.subject,
                               content=post.content)
        elif not self.user:
            return self.redirect('/login')
        else:
            error = "can not edit this post as you are not the author"
            comments = db.GqlQuery(
                "select * from Comment order by created desc"
            )
            self.render("permalink.html", post=post, comments=comments,
                        error=error)

    def post(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)

        if post is not None and self.user and self.user.name == post.author:
            subject = self.request.get('subject')
            content = self.request.get('content')
            if subject and content:
                post.subject = subject
                post.content = content
                post.put()
                self.redirect('/%s' % str(post.key().id()))
            else:
                error = "subject and content, please!"
                self.render("editpost.html", subject=subject, content=content,
                            error=error)


class DeletePost(BlogHandler):
    def get(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)

        if post is not None and self.user and self.user.name == post.author:
            post.delete()
            self.redirect('/deletepostmessage')
        elif not self.user:
            return self.redirect('/login')
        else:
            error = "You don't have permission to delete this post"
            comments = db.GqlQuery(
                "select * from Comment order by created desc"
            )
            self.render("permalink.html", post=post,
                        comments=comments, error=error)


class DeletePostMsg(BlogHandler):
    def get(self):
        self.render("deletepost.html")


class AddComment(BlogHandler):
    def get(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)

        if not post:
            return self.redirect('/')

        if self.user:
            self.render("addcomment.html", post=post)
        else:
            self.redirect("/login")

    def post(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)
        if not self.user:
            return self.redirect('/login')

        content = self.request.get('content')

        if content:
            c = Comment(parent=key, post_id=int(post_id), content=content,
                        author=self.user.name)
            c.put()
            self.redirect('/%s' % str(post.key().id()))
        else:
            error = "content please!"
            self.render("addcomment.html", post=post, error=error)


# Will toggle if the user like or unlike post only for post not their own
class ToggleLike(BlogHandler):
    def get(self, post_id):
        key = db.Key.from_path('Post', int(post_id), parent=blog_key())
        post = db.get(key)
        if not self.user:
            self.redirect("/login")
        else:
            user_id = self.user.name
            post_id = int(post_id)

            if self.user and self.user.name == post.author:
                return self.redirect("/")

            like = Like.all().filter(
                'user_id =', user_id
            ).filter('post_id =', post_id).get()

            print("This is like")
            print(like)
            if like:
                like.delete()
                post.likes -= 1
                post.put()
                self.redirect('/' + str(post.key().id()))
            else:
                like = Like(parent=key, post_id=post_id, user_id=user_id)
                post.likes += 1
                like.put()
                post.put()

                self.redirect('/' + str(post.key().id()))


class EditComment(BlogHandler):
    def get(self, post_id, comment_id):
        postKey = db.Key.from_path('Post', int(post_id), parent=blog_key())
        key = db.Key.from_path('Comment', int(comment_id), parent=postKey)
        comment = db.get(key)
        post = db.get(postKey)

        if not post or not comment:
            return self.redirect('/')

        if (self.user and self.user.name == comment.author):
            self.render("editcomment.html", post=post, content=comment.content)
        elif not self.user:
            self.redirect("/login")
        else:
            error = "unable to edit comment"
            comments = db.GqlQuery(
                "select * from Comment order by created desc"
            )
            self.render("permalink.html", post=post, comments=comments,
                        error=error)

    def post(self, post_id, comment_id):
        postKey = db.Key.from_path('Post', int(post_id), parent=blog_key())
        key = db.Key.from_path('Comment', int(comment_id), parent=postKey)
        comment = db.get(key)
        post = db.get(postKey)

        if not self.user:
            return self.redirect('/login')

        content = self.request.get('content')

        if (
            comment is not None and content and
            self.user and self.user.name == comment.author
        ):
            comment.content = content
            comment.put()
            self.redirect('/%s' % str(post.key().id()))
        else:
            error = "content, please!"
            self.render("editcomment.html", post=post, content=content,
                        error=error)


class DeleteComment(BlogHandler):
    def get(self, post_id, comment_id):
        postKey = db.Key.from_path('Post', int(post_id), parent=blog_key())
        key = db.Key.from_path('Comment', int(comment_id), parent=postKey)
        comment = db.get(key)
        post = db.get(postKey)

        if (
            comment is not None and self.user and
            self.user.name == comment.author
        ):
            comment.delete()
            self.redirect('/%s' % str(post.key().id()))

        elif not self.user:
            self.redirect('/login')

        else:
            error = "You don't have permission to delete this comment"
            comments = db.GqlQuery(
                    "select * from Comment order by created desc"
                )
            self.render("permalink.html", post=post, comments=comments,
                        error=error)


class DeleteCommentMsg(BlogHandler):
    def get(self):
        self.render("deletepost.html")


class Signup(BlogHandler):
    def get(self):
        self.render("signup-form.html")

    def post(self):
        have_error = False
        self.username = self.request.get('username')
        self.password = self.request.get('password')
        self.verify = self.request.get('verify')
        self.email = self.request.get('email')

        params = dict(username=self.username,
                      email=self.email)

        if not blogfunc.valid_username(self.username):
            params['error_username'] = "That's not a valid username."
            have_error = True

        if not blogfunc.valid_password(self.password):
            params['error_password'] = "That wasn't a valid password."
            have_error = True
        elif self.password != self.verify:
            params['error_verify'] = "Your passwords didn't match."
            have_error = True

        if not blogfunc.valid_email(self.email):
            params['error_email'] = "That's not a valid email."
            have_error = True

        if have_error:
            self.render('signup-form.html', **params)
        else:
            self.done()

    def done(self, *a, **kw):
        raise NotImplementedError


class Register(Signup):
    def done(self):
        # make sure the user doesn't already exist
        u = User.by_name(self.username)
        if u:
            msg = 'That user already exists.'
            self.render('signup-form.html', error_username=msg)
        else:
            u = User.register(self.username, self.password, self.email)
            u.put()

            self.login(u)
            self.redirect('/')


class Login(BlogHandler):
    def get(self):
        self.render('login-form.html')

    def post(self):
        username = self.request.get('username')
        password = self.request.get('password')

        u = User.login(username, password)
        if u:
            self.login(u)
            self.redirect('/')
        else:
            msg = 'Invalid login'
            self.render('login-form.html', error=msg)


class Logout(BlogHandler):
    def get(self):
        self.logout()
        self.redirect('/')


app = webapp2.WSGIApplication([('/', BlogFront),
                               ('/([0-9]+)/editpost', EditPost),
                               ('/([0-9]+)/deletepost', DeletePost),
                               ('/([0-9]+)/addcomment', AddComment),
                               ('/([0-9]+)/togglelike', ToggleLike),
                               ('/([0-9]+)/([0-9]+)/editcomment', EditComment),
                               ('/([0-9]+)/([0-9]+)/deletecomment',
                                DeleteComment),
                               ('/([0-9]+)', PostPage),
                               ('/newpost', NewPost),
                               ('/signup', Register),
                               ('/login', Login),
                               ('/logout', Logout),
                               ('/deletepostmessage', DeleteCommentMsg),
                               ],
                              debug=True)
