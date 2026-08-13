"""Tests du stockage chiffré des credentials sociaux."""
import unittest

from cryptography.fernet import Fernet

from api.security.social_credentials import SocialCredentialCipher


class SocialCredentialCipherTests(unittest.TestCase):
    def setUp(self):
        self.cipher = SocialCredentialCipher(Fernet.generate_key().decode("ascii"))

    def test_token_roundtrip_does_not_store_plaintext(self):
        encrypted = self.cipher.encrypt("secret-access-token")
        self.assertNotIn("secret-access-token", encrypted)
        self.assertEqual(self.cipher.decrypt(encrypted), "secret-access-token")

    def test_missing_or_invalid_key_is_rejected(self):
        with self.assertRaises(RuntimeError):
            SocialCredentialCipher("")
        with self.assertRaises(RuntimeError):
            SocialCredentialCipher("invalid")

    def test_tampered_ciphertext_is_rejected_without_leaking_it(self):
        encrypted = self.cipher.encrypt("secret")
        with self.assertRaisesRegex(RuntimeError, "ne peut pas être déchiffré"):
            self.cipher.decrypt(encrypted[:-2] + "xx")


if __name__ == "__main__":
    unittest.main()
