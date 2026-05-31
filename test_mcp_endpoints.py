"""Test MCP admin endpoints."""
import httpx
import json

BASE_URL = "http://127.0.0.1:8000"

def test_mcp_endpoints():
    print("=" * 60)
    print("Testing MCP Admin Endpoints")
    print("=" * 60)
    
    # Test 1: GET /api/admin/mcp (list servers)
    print("\n1. GET /api/admin/mcp (list servers)")
    try:
        with httpx.Client() as client:
            r = client.get(f"{BASE_URL}/api/admin/mcp")
        print(f"   Status: {r.status_code}")
        print(f"   Response: {json.dumps(r.json(), indent=2)}")
        assert r.status_code == 200
        assert "servers" in r.json()
        print("   [PASS]")
    except Exception as e:
        print(f"   [FAIL]: {e}")
        return False
    
    # Test 2: POST /api/admin/mcp (add server)
    print("\n2. POST /api/admin/mcp (add server)")
    try:
        server_config = {
            "name": "test-server",
            "transport": "stdio",
            "command": "echo test",
            "url": None
        }
        with httpx.Client() as client:
            r = client.post(f"{BASE_URL}/api/admin/mcp", json=server_config)
        print(f"   Status: {r.status_code}")
        print(f"   Response: {json.dumps(r.json(), indent=2)}")
        assert r.status_code == 200
        assert r.json().get("ok") == True
        print("   [PASS]")
    except Exception as e:
        print(f"   [FAIL]: {e}")
        return False
    
    # Test 3: GET /api/admin/mcp (verify server added)
    print("\n3. GET /api/admin/mcp (verify server added)")
    try:
        with httpx.Client() as client:
            r = client.get(f"{BASE_URL}/api/admin/mcp")
        print(f"   Status: {r.status_code}")
        data = r.json()
        print(f"   Total servers: {data['total']}")
        assert r.status_code == 200
        assert data["total"] == 1
        assert data["servers"][0]["name"] == "test-server"
        print("   [PASS]")
    except Exception as e:
        print(f"   [FAIL]: {e}")
        return False
    
    # Test 4: POST /api/admin/mcp (duplicate server - should fail)
    print("\n4. POST /api/admin/mcp (duplicate server - should fail)")
    try:
        with httpx.Client() as client:
            r = client.post(f"{BASE_URL}/api/admin/mcp", json=server_config)
        print(f"   Status: {r.status_code}")
        print(f"   Response: {json.dumps(r.json(), indent=2)}")
        assert r.status_code == 409  # Conflict
        print("   [PASS]")
    except Exception as e:
        print(f"   [FAIL]: {e}")
        return False
    
    # Test 5: DELETE /api/admin/mcp/{name} (remove server)
    print("\n5. DELETE /api/admin/mcp/test-server (remove server)")
    try:
        with httpx.Client() as client:
            r = client.delete(f"{BASE_URL}/api/admin/mcp/test-server")
        print(f"   Status: {r.status_code}")
        print(f"   Response: {json.dumps(r.json(), indent=2)}")
        assert r.status_code == 200
        assert r.json().get("ok") == True
        print("   [PASS]")
    except Exception as e:
        print(f"   [FAIL]: {e}")
        return False
    
    # Test 6: GET /api/admin/mcp (verify server removed)
    print("\n6. GET /api/admin/mcp (verify server removed)")
    try:
        with httpx.Client() as client:
            r = client.get(f"{BASE_URL}/api/admin/mcp")
        print(f"   Status: {r.status_code}")
        data = r.json()
        print(f"   Total servers: {data['total']}")
        assert r.status_code == 200
        assert data["total"] == 0
        print("   [PASS]")
    except Exception as e:
        print(f"   [FAIL]: {e}")
        return False
    
    # Test 7: DELETE /api/admin/mcp/{name} (non-existent - should fail)
    print("\n7. DELETE /api/admin/mcp/nonexistent (should fail)")
    try:
        with httpx.Client() as client:
            r = client.delete(f"{BASE_URL}/api/admin/mcp/nonexistent")
        print(f"   Status: {r.status_code}")
        print(f"   Response: {json.dumps(r.json(), indent=2)}")
        assert r.status_code == 404
        print("   [PASS]")
    except Exception as e:
        print(f"   [FAIL]: {e}")
        return False
    
    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)
    return True

if __name__ == "__main__":
    test_mcp_endpoints()
