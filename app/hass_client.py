"""Home Assistant client wrapper with async support."""
import asyncio
import logging
import os
import gc
import sys
import weakref
from typing import Optional, Dict, Any, List, cast

# Configure logging
logger = logging.getLogger(__name__)

# Apply a monkey patch to fix CachedSession cleanup
try:
    import aiohttp_client_cache
    original_init = aiohttp_client_cache.CachedSession.__init__
    
    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # Add a finalizer to ensure the session is closed
        weakref.finalize(self, lambda: asyncio.run_coroutine_threadsafe(self.close(), asyncio.get_event_loop()) if self._connector and not self._connector.closed else None)
    
    aiohttp_client_cache.CachedSession.__init__ = patched_init
    logger.info("Applied monkey patch to aiohttp_client_cache.CachedSession")
except (ImportError, AttributeError) as e:
    logger.warning(f"Could not apply monkey patch: {e}")

# Now import the client after the monkey patch
from homeassistant_api import Client


class HassClient:
    """Wrapper around Home Assistant API Client with async support."""

    def __init__(self):
        """Initialize the Home Assistant client."""
        # Get connection details from environment
        url = os.environ.get("HA_URL", "http://localhost:8123")
        token = os.environ.get("HA_TOKEN")
        
        if not token:
            logger.error("HA_TOKEN environment variable is required")
            raise ValueError("HA_TOKEN environment variable is required")
        
        # Always append /api to the URL
        url = f"{url.rstrip('/')}/api"
        
        logger.info(f"Connecting to Home Assistant at {url}...")
        
        # Initialize client with async support
        self._client = Client(url, token, use_async=True)
    
    async def verify_connection(self) -> Dict[str, Any]:
        """Verify the connection to Home Assistant and return config."""
        try:
            config = await self._client.async_get_config()
            logger.info(f"Connected to Home Assistant {config.get('version', 'unknown')}")
            return cast(Dict[str, Any], config)
        except Exception as e:
            logger.error(f"Failed to connect to Home Assistant: {e}")
            raise
    
    async def get_version(self) -> str:
        """Get the Home Assistant version."""
        config = await self._client.async_get_config()
        return config.get("version", "unknown")
    
    async def get_states(self):
        """Get all entity states from Home Assistant."""
        return await self._client.async_get_states()
    
    async def trigger_service(self, domain: str, service: str, **data):
        """Call a service in Home Assistant."""
        return await self._client.async_trigger_service(domain, service, **data)
    
    async def close(self):
        """Close the client connection and clean up resources."""
        try:
            # Access the underlying client session
            if hasattr(self._client, 'raw_client'):
                client = self._client.raw_client
                if hasattr(client, 'session'):
                    session = client.session
                    
                    # Try different session closing approaches
                    try:
                        # Close the main session
                        if hasattr(session, 'close') and callable(session.close):
                            if asyncio.iscoroutinefunction(session.close):
                                await session.close()
                            else:
                                session.close()
                        
                        # Also try to close the connector if available
                        if hasattr(session, '_connector') and hasattr(session._connector, 'close'):
                            if asyncio.iscoroutinefunction(session._connector.close):
                                await session._connector.close()
                            else:
                                session._connector.close()
                                
                        # For aiohttp_client_cache CachedSession
                        if hasattr(session, 'raw_session') and hasattr(session.raw_session, 'close'):
                            if asyncio.iscoroutinefunction(session.raw_session.close):
                                await session.raw_session.close()
                            else:
                                session.raw_session.close()
                                
                        logger.info("Closed aiohttp session")
                    except Exception as inner_e:
                        logger.warning(f"Error closing specific session components: {inner_e}")
        except Exception as e:
            logger.warning(f"Error closing client session: {e}")
        
        # Forcefully close all aiohttp sessions
        try:
            # Find and close all aiohttp sessions
            for obj in gc.get_objects():
                if isinstance(obj, aiohttp_client_cache.CachedSession) and hasattr(obj, 'close'):
                    if not getattr(obj, '_closed', False):
                        try:
                            if asyncio.iscoroutinefunction(obj.close):
                                await obj.close()
                            else:
                                obj.close()
                            logger.info("Closed orphaned CachedSession")
                        except Exception as e:
                            logger.warning(f"Error closing orphaned session: {e}")
        except Exception as e:
            logger.warning(f"Error during global session cleanup: {e}")
            
        # Cancel any tasks that might be keeping sessions open
        try:
            # Get all tasks and cancel those that might be keeping sessions open
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                logger.info(f"Canceled {len(tasks)} lingering tasks")
        except Exception as e:
            logger.warning(f"Error during task cleanup: {e}")
        
        logger.info("Disconnected from Home Assistant")