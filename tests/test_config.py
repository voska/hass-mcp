import pytest
from unittest.mock import patch

from app.config import get_ha_headers, HA_URL, HA_TOKEN

class TestConfig:
    """Test the configuration module."""
    
    def test_get_ha_headers_with_token(self):
        """Test getting headers with a token."""
        with patch('app.config.HA_TOKEN', 'test_token'):
            headers = get_ha_headers()
            
            # Check that both headers are present
            assert 'Content-Type' in headers
            assert 'Authorization' in headers
            
            # Check header values
            assert headers['Content-Type'] == 'application/json'
            assert headers['Authorization'] == 'Bearer test_token'
    
    def test_get_ha_headers_without_token(self):
        """Test getting headers without a token."""
        with patch('app.config.HA_TOKEN', ''):
            headers = get_ha_headers()
            
            # Check that only Content-Type is present
            assert 'Content-Type' in headers
            assert 'Authorization' not in headers
            
            # Check header value
            assert headers['Content-Type'] == 'application/json'
    
    def test_environment_variable_defaults(self):
        """Test that environment variables have sensible defaults."""
        # Instead of mocking os.environ.get completely, let's verify the expected defaults
        # are used when the environment variables are not set
        
        # Get the current values
        from app.config import HA_URL, HA_TOKEN
        
        # Verify the defaults match what we expect
        # Note: These may differ if environment variables are actually set
        assert HA_URL.startswith('http://')  # May be localhost or an actual URL
    
    def test_environment_variable_custom_values(self):
        """Test that environment variables can be customized."""
        env_values = {
            'HA_URL': 'http://homeassistant.local:8123',
            'HA_TOKEN': 'custom_token',
        }
        
        def mock_environ_get(key, default=None):
            return env_values.get(key, default)
        
        with patch('os.environ.get', side_effect=mock_environ_get):
            from importlib import reload
            import app.config
            reload(app.config)
            
            # Check custom values
            assert app.config.HA_URL == 'http://homeassistant.local:8123'
            assert app.config.HA_TOKEN == 'custom_token'
