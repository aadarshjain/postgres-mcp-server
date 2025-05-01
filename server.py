# server.py
#
# This script creates a Model Context Protocol (MCP) server that provides tools for
# exploring and querying a PostgreSQL database.

from mcp.server.fastmcp import FastMCP
import pg8000  # PostgreSQL database adapter for Python
import logging
import json
import sys
from typing import Optional, List, Dict, Any
from sqlalchemy.engine.url import make_url  # For parsing database connection strings

# Initialize the MCP server with a friendly name
# This creates the main server object that will expose our tools
mcp = FastMCP("PostgreSQL MCP Server")

# Configure logging to show INFO level messages
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Validate command line arguments - we expect a PostgreSQL connection string
if len(sys.argv) != 2:
    logger.error("Usage: python server.py <postgresql://user:password@host:port/database>")
    sys.exit(1)

# Store the database connection string from command line
dsn = sys.argv[1]
logger.info(f"PostgreSQL DSN: {dsn}")


def database_connection():
    """
    Create and return a new PostgreSQL database connection.
    
    This function parses the DSN (Data Source Name) into components
    and establishes a new connection each time it's called.
    
    Returns:
        A pg8000 connection object for database operations
    """
    logger.info("Connecting to PostgreSQL database...")
    url = make_url(dsn)  # Parse the connection string

    return pg8000.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database=url.database
    )

@mcp.tool(description="Execute a custom SELECT SQL query on the PostgreSQL database.")
def execute_query(query: str):
    """
    Execute a custom SELECT SQL query and return the results.
    
    Args:
        query: A SQL SELECT query to execute
        
    Returns:
        List of dictionaries containing query results, with column names as keys
        
    Security note:
        This function only allows SELECT queries to prevent database modifications
    """
    try:
        # Security check - only allow SELECT queries
        if not query.strip().lower().startswith("select"):
            raise ValueError("Only SELECT queries are allowed.")
        
        conn = database_connection()
        logger.info(f"Executing custom SELECT query: {query}")
        cursor = conn.cursor()
        
        cursor.execute(query)
        results = cursor.fetchall()
        
        # Get column names from the cursor description
        column_names = [desc[0] for desc in cursor.description]
        
        logger.info("Fetched query results successfully.")
        conn.close()
        
        # Convert raw tuple results into a more user-friendly dictionary format
        # where each column name is a key in the dictionary
        formatted_results = []
        for row in results:
            record = {}
            for i, col in enumerate(column_names):
                record[col] = row[i]
            formatted_results.append(record)
        
        return formatted_results
    except Exception as e:
        logger.error(f"Error executing query: {str(e)}")
        return {"error": str(e)}

@mcp.tool(description="List all tables in the current PostgreSQL database.")
def list_tables():
    """
    List all tables in the current PostgreSQL database.
    
    Returns:
        List of table names in the 'public' schema
    """
    try:
        conn = database_connection()
        cursor = conn.cursor()
        
        # Query the information_schema to get all table names in the public schema
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        
        tables = [row[0] for row in cursor.fetchall()]
        logger.info("Fetched table names successfully.")
        conn.close()
        
        return tables
    except Exception as e:
        logger.error(f"Error listing tables: {str(e)}")
        return {"error": str(e)}

@mcp.tool(description="Get the schema definition for a specified table.")
def get_table_schema(table_name: str):
    """
    Get the schema definition for a specified table.
    
    Args:
        table_name: Name of the table to get schema information for
        
    Returns:
        List of dictionaries containing column details (name, type, nullability, default)
    """
    try:
        conn = database_connection()
        cursor = conn.cursor()
        
        # Query the information_schema to get column information for the specified table
        cursor.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
        """, (table_name,))
        
        columns = []
        for row in cursor.fetchall():
            columns.append({
                "column_name": row[0],
                "data_type": row[1],
                "is_nullable": row[2],
                "default_value": row[3]
            })
        
        logger.info(f"Fetched schema for table {table_name} successfully.")
        conn.close()
        
        return columns
    except Exception as e:
        logger.error(f"Error getting schema for table {table_name}: {str(e)}")
        return {"error": str(e)}

@mcp.tool(description="Filter EC2 instances based on specified criteria.")
def filter_instances(filters: Dict[str, str]):
    """
    Filter database records based on specified criteria.
    
    This function allows querying a table with equality filters on specific columns.
    
    Args:
        filters: A dictionary of column:value pairs to filter on, must include 'table_name'
    
    Returns:
        Filtered list of records as dictionaries with column names as keys
        
    Example:
        filter_instances({'table_name': 'ec2_instances', 'region': 'us-west-1'})
    """
    try:
        conn = database_connection()
        cursor = conn.cursor()
        
        # Build WHERE clause from filters
        where_clauses = []
        params = []
        
        for column, value in filters.items():
            where_clauses.append(f"{column} = %s")
            params.append(value)
        
        where_clause = " AND ".join(where_clauses)
        
        # Table name must be explicitly provided in filters
        if "table_name" not in filters:
            raise ValueError("'table_name' is required in filters parameter")
            
        table_name = filters.pop("table_name")
        query = f"SELECT * FROM {table_name}"
        
        if where_clauses:
            query += f" WHERE {where_clause}"
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        column_names = [desc[0] for desc in cursor.description]
        
        logger.info("Fetched filtered instances successfully.")
        conn.close()
        
        # Format the results as a list of dictionaries
        instances = []
        for row in results:
            instance = {}
            for i, col in enumerate(column_names):
                instance[col] = row[i]
            instances.append(instance)
        
        return instances
    except Exception as e:
        logger.error(f"Error filtering instances: {str(e)}")
        return {"error": str(e)}

@mcp.tool(description="Get database statistics and metadata.")
def get_database_stats():
    """
    Get general statistics and metadata about the PostgreSQL database.
    
    This function returns various database metrics including:
    - Database size
    - Number of tables
    - PostgreSQL version
    - Top 5 largest tables with their sizes
    
    Returns:
        Dictionary containing database statistics
    """
    try:
        conn = database_connection()
        cursor = conn.cursor()
        
        # Get database size using PostgreSQL's built-in functions
        cursor.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
        db_size = cursor.fetchone()[0]
        
        # Count tables in the public schema
        cursor.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
        table_count = cursor.fetchone()[0]
        
        # Get PostgreSQL version information
        cursor.execute("SELECT version()")
        version = cursor.fetchone()[0]
        
        # Find the 5 largest tables by total size (including indexes and related objects)
        cursor.execute("""
            SELECT 
                table_name,
                pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) as size
            FROM 
                information_schema.tables
            WHERE 
                table_schema = 'public'
            ORDER BY 
                pg_total_relation_size(quote_ident(table_name)) DESC
            LIMIT 5
        """)
        
        largest_tables = [{"table": row[0], "size": row[1]} for row in cursor.fetchall()]
        
        logger.info("Fetched database statistics successfully.")
        conn.close()
        
        return {
            "database_size": db_size,
            "table_count": table_count,
            "postgres_version": version,
            "largest_tables": largest_tables
        }
    except Exception as e:
        logger.error(f"Error getting database stats: {str(e)}")
        return {"error": str(e)}

# Entry point - only run the server if this file is executed directly
if __name__ == '__main__':
    logger.info("Starting PostgreSQL Data Discovery MCP server...")
    mcp.run()