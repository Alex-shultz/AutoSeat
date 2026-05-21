"""
test_auth.py
============
Unit tests for the auth module (authentication and authorization).

Tests cover:
- Password hashing and verification
- login_required decorator behavior
- Auth routes (login, register, logout)
"""

import pytest
from unittest.mock import MagicMock, patch
from auth import hash_password, verify_password, login_required


class TestPasswordHashing:
    """Tests for password hashing functions."""
    
    def test_hash_password_produces_string(self):
        """Test that hash_password returns a string."""
        result = hash_password("testpassword")
        assert isinstance(result, str)
    
    def test_hash_password_different_salts(self):
        """Test that same password produces different hashes (due to salt)."""
        hash1 = hash_password("samepassword")
        hash2 = hash_password("samepassword")
        # Should be different due to random salt
        assert hash1 != hash2
    
    def test_hash_password_format(self):
        """Test that hash has expected format (salt$hash)."""
        result = hash_password("testpassword")
        assert "$" in result
        salt, dk_hex = result.split("$", 1)
        assert len(salt) == 32  # 16 bytes hex = 32 chars
        assert len(dk_hex) == 64  # 32 bytes hex = 64 chars
    
    def test_verify_password_correct(self):
        """Test verifying correct password."""
        password = "securepassword123"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True
    
    def test_verify_password_incorrect(self):
        """Test verifying incorrect password."""
        password = "securepassword123"
        hashed = hash_password(password)
        assert verify_password("wrongpassword", hashed) is False
    
    def test_verify_password_empty(self):
        """Test verifying empty password."""
        hashed = hash_password("password")
        assert verify_password("", hashed) is False
    
    def test_verify_password_invalid_stored(self):
        """Test verifying with invalid stored hash format."""
        assert verify_password("password", "invalid_format") is False
        assert verify_password("password", "") is False
        assert verify_password("password", None) is False


class TestLoginRequired:
    """Tests for login_required decorator."""
    
    def test_login_required_with_user_id(self):
        """Test that decorated function proceeds when user_id in session."""
        mock_session = {"user_id": 1}
        
        @login_required
        def test_func():
            return "success"
        
        with patch('auth.session', mock_session):
            result = test_func()
            assert result == "success"
    
    def test_login_required_without_user_id(self):
        """Test that decorated function redirects when no user_id."""
        mock_session = {}
        
        @login_required
        def test_func():
            return "should not reach here"
        
        with patch('auth.session', mock_session):
            with patch('auth.flash') as mock_flash:
                with patch('auth.url_for') as mock_url_for:
                    with patch('auth.redirect') as mock_redirect:
                        mock_url_for.return_value = "/auth"
                        mock_redirect.return_value = "redirect_response"
                        result = test_func()
                        
                        mock_flash.assert_called_once_with(
                            "Please log in to continue.", "info"
                        )
                        assert result == "redirect_response"
    
    def test_login_required_preserves_function_name(self):
        """Test that decorator preserves original function name."""
        @login_required
        def my_special_function():
            pass
        
        assert my_special_function.__name__ == "my_special_function"


class TestAuthRoutes:
    """Tests for auth blueprint routes."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask application."""
        from app import create_app
        from database import init_db
        
        app = create_app()
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        
        init_db()
        
        with app.app_context():
            yield app
    
    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return app.test_client()
    
    def test_auth_page_get(self, client):
        """Test GET request to auth page."""
        response = client.get("/auth")
        assert response.status_code == 200
    
    def test_logout_post(self, client):
        """Test POST request to logout."""
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "testuser"
        
        response = client.post("/logout", follow_redirects=True)
        assert response.status_code == 200
    
    def test_register_password_mismatch(self, client):
        """Test registration with mismatched passwords."""
        response = client.post("/auth", data={
            "action": "register",
            "username": "testuser",
            "email": "test@example.com",
            "password": "password123",
            "confirm": "differentpassword",
        }, follow_redirects=True)
        
        assert response.status_code == 200
    
    def test_register_short_username(self, client):
        """Test registration with short username."""
        response = client.post("/auth", data={
            "action": "register",
            "username": "ab",  # Too short
            "email": "test@example.com",
            "password": "password123",
            "confirm": "password123",
        }, follow_redirects=True)
        
        assert response.status_code == 200
    
    def test_register_short_password(self, client):
        """Test registration with short password."""
        response = client.post("/auth", data={
            "action": "register",
            "username": "validuser",
            "email": "test@example.com",
            "password": "short",  # Too short
            "confirm": "short",
        }, follow_redirects=True)
        
        assert response.status_code == 200
